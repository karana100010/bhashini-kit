"""Live (streaming) ASR example, kept separate from the HTTP proxy.

Run:   uvicorn stream_app:app --app-dir server --port 8766     (or: docker compose up)
Then open http://localhost:8766/

The browser opens a plain WebSocket to /ws/asr. This server opens Dhruva's socket.io stream with
the API key, so the key never reaches the browser.

Browser -> server
  text   {"type": "start", "language": "hi", "service_id"?}   first message (service_id: an ASR model)
  binary 16 kHz mono 16-bit little-endian PCM         as it is recorded (any chunk size)
  text   {"type": "flush"}                            end of an utterance: finalise text so far
  text   {"type": "stop"}                             finalise and close
Server -> browser
  {"type": "ready"} | {"type": "partial", "text"} | {"type": "final", "text"}
  {"type": "error", "message"} | {"type": "end"}
"""
import asyncio
import json
import logging
from pathlib import Path

import socketio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import bhashini_client as bhashini
import config
import models
import storage

log = logging.getLogger('bhashini.stream')
WEB = Path(__file__).resolve().parent.parent / 'web'
STREAMING = {'responseFrequencyInSecs': 1, 'responseTaskSequenceDepth': 1}

app = FastAPI(title='Bhashini streaming ASR')


class Bridge:
    """One Dhruva socket.io session for one browser WebSocket."""

    def __init__(self, websocket, language, service_id=None):
        self.websocket, self.language, self.service_id = websocket, language, service_id
        self.sio = socketio.AsyncClient(reconnection=False)
        self.ready, self.finished = asyncio.Event(), asyncio.Event()
        self.sio.on('ready', self._on_ready)
        self.sio.on('response', self._on_response)
        self.sio.on('terminate', self._on_terminate)
        self.sio.on('abort', self._on_abort)
        self.sio.on('disconnect', self._on_terminate)

    async def _send(self, message):
        try:
            await self.websocket.send_text(json.dumps(message, ensure_ascii=False))
        except (RuntimeError, WebSocketDisconnect):
            pass

    async def _on_ready(self, *_):
        self.ready.set()
        await self._send({'type': 'ready'})

    async def _on_response(self, response, meta=None, *_):
        try:
            text = ' '.join(o.get('source', '') for o in response['pipelineResponse'][0]['output']).strip()
        except (KeyError, IndexError, TypeError):
            return
        final = not (meta or {}).get('isIntermediateResult', True)
        await self._send({'type': 'final' if final else 'partial', 'text': text})

    async def _on_terminate(self, *_):
        self.finished.set()

    async def _on_abort(self, message=None, *_):
        await self._send({'type': 'error', 'message': f'Bhashini stopped the stream: {message or "aborted"}.'})
        self.finished.set()

    async def open(self):
        key = config.get('BHASHINI_API_KEY')
        if not key:
            raise bhashini.BhashiniError('not_configured', 'BHASHINI_API_KEY is not set. Add it on the Settings page.')
        await self.sio.connect(config.get('BHASHINI_STREAM_URL'), socketio_path='/socket.io',
                               transports=['websocket'], auth={'authorization': key}, wait_timeout=15)
        task_config = {'language': {'sourceLanguage': self.language}, 'samplingRate': 16000,
                       'audioFormat': 'wav', 'encoding': None}
        if service := self.service_id or bhashini._service('STREAM_ASR', self.language):
            task_config['serviceId'] = service
        await self.sio.emit('start', ([{'taskType': 'asr', 'config': task_config}], STREAMING))
        await asyncio.wait_for(self.ready.wait(), 15)

    async def audio(self, pcm):
        await self.sio.emit('data', ({'audio': [{'audioContent': pcm}]}, STREAMING, False, False))

    async def flush(self):
        await self.sio.emit('data', (None, None, True, False))

    async def close(self):
        if self.sio.connected:
            try:
                await self.sio.emit('data', (None, None, True, True))
                await asyncio.wait_for(self.finished.wait(), 8)
            except (asyncio.TimeoutError, socketio.exceptions.SocketIOError):
                pass
            await self.sio.disconnect()


@app.websocket('/ws/asr')
async def asr_stream(websocket: WebSocket):
    await websocket.accept()
    bridge = None
    try:
        start = json.loads(await websocket.receive_text())
        language = start.get('language', 'hi')
        if start.get('type') != 'start' or language not in bhashini.LANGUAGES:
            await websocket.send_json({'type': 'error', 'message': 'First message must be {"type":"start","language":"hi"}.'})
            return
        service_id = start.get('service_id') or None
        if service_id:
            model = models.find('asr', service_id)
            if not model or not models.supports(model, language):
                await websocket.send_json({'type': 'error', 'message': f'{service_id} does not support {language}.'})
                return
        bridge = Bridge(websocket, language, service_id)
        await bridge.open()
        while True:
            message = await websocket.receive()
            if message['type'] == 'websocket.disconnect':
                break
            if message.get('bytes'):
                await bridge.audio(message['bytes'])
            elif message.get('text'):
                kind = json.loads(message['text']).get('type')
                if kind == 'flush':
                    await bridge.flush()
                elif kind == 'stop':
                    await bridge.close()
                    await websocket.send_json({'type': 'end'})
                    break
    except WebSocketDisconnect:
        pass
    except bhashini.BhashiniError as error:
        await websocket.send_json({'type': 'error', 'message': error.message})
    except (socketio.exceptions.ConnectionError, asyncio.TimeoutError) as error:
        log.warning('stream connect failed: %r', error)
        await websocket.send_json({'type': 'error', 'message': 'Could not open the Bhashini stream (check the API key).'})
    finally:
        if bridge:
            await bridge.close()
        try:
            await websocket.close()
        except RuntimeError:
            pass


class SaveRequest(BaseModel):
    text: str = Field(max_length=100_000)
    language: str = Field(default='', max_length=4)
    title: str = Field(default='', max_length=120)
    audio_content: str | None = Field(default=None, max_length=25_700_000)


@app.post('/api/transcripts')
async def save_transcript(body: SaveRequest):
    """Same store as the HTTP service, so live transcripts show up there too."""
    try:
        return storage.save(body.text, body.language, 'stream', body.audio_content, body.title)
    except storage.StorageError as error:
        return JSONResponse({'error': {'code': 'invalid_transcript', 'message': str(error)}}, status_code=422)


@app.get('/api/models')
async def asr_models():
    return {'models': {'asr': models.MODELS['asr']}}


@app.get('/healthz')
async def health():
    return {'ok': True, 'key_set': bool(config.get('BHASHINI_API_KEY'))}


@app.get('/pcm-worklet.js')
async def worklet():
    return FileResponse(WEB / 'pcm-worklet.js', media_type='text/javascript')


app.mount('/', StaticFiles(directory=WEB / 'stream', html=True), name='stream')
