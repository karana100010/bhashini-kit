"""HTTP proxy so any UI can use Bhashini without seeing the API key. Also serves the demo UI.

Run:   uvicorn app:app --app-dir server --port 8765     (or: docker compose up)
Then open http://localhost:8765/

All service endpoints are JSON POST under /api/bhashini/ (see README "HTTP API reference").
Errors:  {error: {code, message}} with a 4xx/5xx status.

The live-streaming ASR example is a separate service: server/stream_app.py (port 8766).
"""
import hmac
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import bhashini_client as bhashini
import config
import storage

app = FastAPI(title='Bhashini proxy')

# Only needed if your UI is served from a different origin than this server. Read at startup.
origins = [o.strip() for o in config.get('ALLOWED_ORIGINS').split(',') if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST'],
                       allow_headers=['Content-Type', 'X-Access-Code'])



@app.middleware('http')
async def access_code(request: Request, call_next):
    """With BHASHINI_ACCESS_CODE set, every /api call needs a matching X-Access-Code header."""
    path = request.url.path
    if config.ACCESS_CODE and path.startswith('/api/') and path != '/api/features':
        sent = request.headers.get('x-access-code', '')
        if not hmac.compare_digest(sent.encode(), config.ACCESS_CODE.encode()):
            return _error('access_denied', 'Enter the access code to use this service.', 401)
    if config.HOSTED and (path.startswith('/api/transcripts') or
                          (path.startswith('/api/settings') and request.method == 'PUT')):
        return _error('not_available', 'Not available in the hosted version. Run the Docker version for this.', 403)
    return await call_next(request)


@app.get('/api/features')
async def features():
    """What this deployment supports, so the UI can hide the rest."""
    return {'hosted': config.HOSTED, 'access_required': bool(config.ACCESS_CODE),
            'settings_writable': not config.HOSTED, 'transcripts': not config.HOSTED, 'stream': not config.HOSTED}


AUDIO = 25_700_000  # base64 of 10 min of 16 kHz 16-bit mono WAV
SHORT_AUDIO = 1_921_000  # 45 s
Lang = Field(default='hi', min_length=2, max_length=4)


class AsrRequest(BaseModel):
    audio_content: str = Field(max_length=AUDIO)
    language: str = Field(default='hi', min_length=2, max_length=4, description="language code or 'auto'")


class AudioRequest(BaseModel):
    audio_content: str = Field(max_length=AUDIO)


class SpeechTranslateRequest(BaseModel):
    audio_content: str = Field(max_length=SHORT_AUDIO)
    source: str = Lang
    target: str = Field(default='en', min_length=2, max_length=4)
    speak: bool = False
    gender: str | None = Field(default=None, pattern='^(male|female)$')


class TranslateRequest(BaseModel):
    text: str = Field(max_length=4000)
    source: str = 'en'
    target: str = 'hi'


class TtsRequest(BaseModel):
    text: str = Field(max_length=4000)
    language: str = Lang
    gender: str | None = Field(default=None, pattern='^(male|female)$')


class TransliterateRequest(BaseModel):
    text: str = Field(max_length=1000)
    source: str = 'en'
    target: str = 'hi'
    sentence: bool = True
    suggestions: int = Field(default=5, ge=1, le=10)


class TextRequest(BaseModel):
    text: str = Field(max_length=4000)


class NerRequest(BaseModel):
    text: str = Field(max_length=4000)
    language: str = Lang


class OcrRequest(BaseModel):
    image_content: str | None = Field(default=None, max_length=14_000_000)
    image_url: str | None = Field(default=None, max_length=2000)
    language: str = Lang


class SaveRequest(BaseModel):
    text: str = Field(max_length=100_000)
    language: str = Field(default='', max_length=4)
    source: str = Field(default='asr', max_length=20)
    title: str = Field(default='', max_length=120)
    audio_content: str | None = Field(default=None, max_length=AUDIO)


async def _call(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except bhashini.BhashiniError as error:
        return _error(error.code, error.message, error.status)


def _error(code, message, status):
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


# --- services -------------------------------------------------------------------------------

@app.post('/api/bhashini/asr')
async def asr(body: AsrRequest):
    return await _call(bhashini.transcribe, body.audio_content, body.language)


@app.post('/api/bhashini/detect-audio-language')
async def detect_audio_language(body: AudioRequest):
    return await _call(bhashini.detect_audio_language, body.audio_content)


@app.post('/api/bhashini/speech-translate')
async def speech_translate(body: SpeechTranslateRequest):
    return await _call(bhashini.speech_translate, body.audio_content, body.source, body.target,
                       body.speak, body.gender)


@app.post('/api/bhashini/denoise')
async def denoise(body: AudioRequest):
    return await _call(bhashini.denoise, body.audio_content)


@app.post('/api/bhashini/translate')
async def translate(body: TranslateRequest):
    return await _call(bhashini.translate, body.text, body.source, body.target)


@app.post('/api/bhashini/tts')
async def tts(body: TtsRequest):
    return await _call(bhashini.synthesize, body.text, body.language, body.gender)


@app.post('/api/bhashini/transliterate')
async def transliterate(body: TransliterateRequest):
    return await _call(bhashini.transliterate, body.text, body.source, body.target, body.sentence, body.suggestions)


@app.post('/api/bhashini/detect-language')
async def detect_language(body: TextRequest):
    return await _call(bhashini.detect_language, body.text)


@app.post('/api/bhashini/ner')
async def ner(body: NerRequest):
    return await _call(bhashini.entities, body.text, body.language)


@app.post('/api/bhashini/ocr')
async def ocr(body: OcrRequest):
    return await _call(bhashini.ocr, body.language, body.image_content, body.image_url)


# --- saved transcripts ----------------------------------------------------------------------

@app.post('/api/transcripts')
async def save_transcript(body: SaveRequest):
    try:
        return storage.save(body.text, body.language, body.source, body.audio_content, body.title)
    except storage.StorageError as error:
        return _error('invalid_transcript', str(error), 422)


@app.get('/api/transcripts')
async def list_transcripts():
    return {'transcripts': storage.listing()}


@app.get('/api/transcripts/{entry_id}.{ext}')
async def transcript_file(entry_id: str, ext: str):
    file = storage.path(entry_id, 'json' if ext == 'txt' else ext)
    if not file:
        return _error('not_found', 'No such transcript.', 404)
    if ext == 'txt':
        text = json.loads(file.read_text(encoding='utf-8'))['text']
        return PlainTextResponse(text, headers={'Content-Disposition': f'attachment; filename="{entry_id}.txt"'})
    return FileResponse(file, filename=file.name)


@app.delete('/api/transcripts/{entry_id}')
async def delete_transcript(entry_id: str):
    return {'deleted': storage.delete(entry_id)}


# --- settings (writes config/bhashini.conf) -------------------------------------------------

@app.get('/api/settings')
async def get_settings():
    return config.snapshot()


@app.put('/api/settings')
async def put_settings(body: dict[str, str]):
    try:
        config.save(body)
    except ValueError as error:
        return _error('invalid_setting', str(error), 422)
    except OSError as error:
        return _error('not_writable', f'Could not write {config.CONF_PATH}: {error.strerror}.', 500)
    return config.snapshot()


@app.post('/api/settings/test')
async def test_settings():
    """Checks the saved key with a one-word translation."""
    result = await _call(bhashini.translate, 'Hello', 'en', 'hi')
    return result if isinstance(result, JSONResponse) else {'ok': True, 'sample': result['text']}


@app.get('/healthz')
async def health():
    return {'ok': True, 'key_set': bool(config.get('BHASHINI_API_KEY'))}


# Serves the demo UI and the browser module from ../web.
app.mount('/', StaticFiles(directory=Path(__file__).resolve().parent.parent / 'web', html=True), name='web')
