# Bhashini kit

Drop-in Bhashini (Dhruva) language services for GramStack and any chatbot UI. It runs as two Docker
services: an **HTTP proxy with a demo UI**, and a separate **live (socket) ASR** example.

| Service | What it does | GramStack use | Endpoint |
|---|---|---|---|
| **ASR** | speech → text, up to 10 min, optional auto language detection | voice questions, SHG minutes | `POST /api/bhashini/asr` |
| **TTS** | text → speech | read-back of drafts and answers | `POST /api/bhashini/tts` |
| **NMT** | text → text translation | answers in the member's language | `POST /api/bhashini/translate` |
| **Voice translate** | ASR → NMT → TTS in one call | voice in, voice out in another language | `POST /api/bhashini/speech-translate` |
| **Transliteration** *(new)* | same words, other script (`namaste` → `नमस्ते`) | names typed on English keyboards | `POST /api/bhashini/transliterate` |
| **Text language detection** *(new)* | which language is this text | route WhatsApp text | `POST /api/bhashini/detect-language` |
| **Audio language detection** *(new)* | which language is being spoken | "language detected" step before ASR | `POST /api/bhashini/detect-audio-language` |
| **NER** *(new)* | people, places, organisations in Indic text | member names in meeting notes | `POST /api/bhashini/ner` |
| **OCR** *(new)* | printed text in a photo | registers, passbooks, notices | `POST /api/bhashini/ocr` |
| **Denoiser** *(new)* | removes background noise | field and IVR recordings | `POST /api/bhashini/denoise` |
| **Saved transcripts** *(new)* | save ASR/live text (+ audio) on the server | keep meeting records | `/api/transcripts` |
| **Live ASR** *(new, separate service)* | words appear while you speak | live captions, long meetings | `ws://…:8766/ws/asr` |

The services were picked from the Bhashini Postman collection ("Bhashini API - Prod Documentation")
and GramStack's design (language service block B). Not included: voice cloning, image language
detection, speaker enrollment/verification and pipeline feedback (not GramStack needs), and speaker or
language diarization (no service ID for them works with an inference key; they need ULCA config
access).

```
bhashini_kit/
├── docker-compose.yml       ← http (8765) + asr-stream (8766) + test profile
├── Dockerfile               ← one image, both services
├── config/
│   ├── bhashini.conf        ← API key + service IDs (git-ignored; written by the Settings page)
│   └── bhashini.conf.example
├── data/transcripts/        ← saved transcripts (.json + .wav)
├── server/
│   ├── bhashini_client.py   ← pure Python client for every service
│   ├── config.py            ← reads/writes config/bhashini.conf
│   ├── models.py            ← selectable Bhashini models per task + languages
│   ├── storage.py           ← saved transcripts
│   ├── app.py               ← HTTP proxy + UI            (port 8765)
│   └── stream_app.py        ← live ASR socket bridge + UI (port 8766)
├── web/
│   ├── index.html, app.js, app.css   ← demo UI for all HTTP services + Settings
│   ├── bhashini.js          ← browser ES module (mic, ASR, TTS, all services, fileToWav)
│   ├── pcm-worklet.js       ← AudioWorklet used by the mic recorder
│   └── stream/              ← live ASR page + stream.js (served by stream_app.py)
└── tests/test_endpoints.py  ← end-to-end tests of every endpoint
```

## The one rule: the key stays on the server

The browser **never** calls Bhashini directly. Your UI calls these services, and they add the
`Authorization` header. This applies to the live socket too: the browser opens a WebSocket to
`stream_app.py`, which opens the Dhruva socket.io stream with the key.

```
Browser ──HTTP──▶ http :8765 /api/bhashini/* ──(+ key)──▶ dhruva-api.bhashini.gov.in/services/inference/…
Browser ──WS────▶ asr-stream :8766 /ws/asr   ──(+ key)──▶ wss://dhruva-api.bhashini.gov.in/socket.io
                           both read config/bhashini.conf, both save to data/transcripts
```

## 1. Quick start (Docker)

```bash
docker compose up -d --build
```

* <http://localhost:8765>: all services, Saved transcripts, Settings
* <http://localhost:8766>: live ASR (socket) example

On first run, open **Settings**, paste the Dhruva inference key and click **Save settings**, then
**Test key**. This writes `config/bhashini.conf`. Both containers re-read the file when it changes, so
no restart is needed. You can also copy `config/bhashini.conf.example` to `config/bhashini.conf`
and edit it by hand.

> Ports are bound to `127.0.0.1` because the Settings page can change the key. To expose the kit on a
> network, put it behind a reverse proxy with authentication, or remove the Settings routes.
> The microphone only works on **HTTPS or `localhost`**.

No Docker? `pip install -r requirements.txt`, then run
`uvicorn app:app --app-dir server --port 8765` and `uvicorn stream_app:app --app-dir server --port 8766`.

On a Mac without Docker Desktop: `brew install colima docker docker-compose && colima start`.

## 1a. Choosing models

Every panel has a **Model** menu listing the Bhashini models that support the selected language(s), from
the [official list](https://dibd-bhashini.gitbook.io/bhashini-apis/available-models-for-usage)
(catalog: `server/models.py`, also served at `GET /api/models`). The **Models** tab shows the full table.
**Default** uses the model from Settings, or lets Bhashini choose. If the configured default can't handle
a language (e.g. NER in English), the kit switches to one that can.

Every model was called with a real key on 2026-10-14. Models marked ⚠ returned a Bhashini-side error
then (IISc Maithili ASR, IITB trilingual NMT, IIITH printed and handwritten OCR) but stay in the list so they
can be retried. Speaker and language diarization (listed by Bhashini) still returned 500 and are not offered.

API: pass `service_id` (or `asr_service_id` / `nmt_service_id` / `tts_service_id` for
`speech-translate`, `service_id` in the live socket's `start` message). Unknown IDs, or IDs that don't
support the language, get a 422.

## 1b. Hosted version (Vercel)

The HTTP app also runs on Vercel as a single Python function (`api/index.py`, `vercel.json`).
Vercel has no persistent disk or sockets, so the hosted version is limited:

| | Docker | Vercel |
|---|---|---|
| All HTTP services + UI | ✓ | ✓ |
| API key | Settings page → `config/bhashini.conf` | Vercel env var `BHASHINI_API_KEY` (Settings is read-only) |
| Saved transcripts (server) | ✓ | hidden; the ⬇ .txt download still works |
| Live socket ASR | ✓ (port 8766) | not available |
| Max audio per request | 10 min | about 1.5 min (Vercel's 4.5 MB request limit) |

Set two environment variables in the Vercel project, then deploy:

```bash
vercel env add BHASHINI_API_KEY production
```

```bash
vercel env add BHASHINI_ACCESS_CODE production
```

```bash
vercel deploy --prod
```

`BHASHINI_ACCESS_CODE` gates the public URL. Visitors enter it once (it is stored in their
browser), and every `/api` call without it gets a 401, so strangers can't spend your Bhashini quota.
Share it only with the field team. If you leave it unset, anyone with the link can use your key.

## 2. Configuration (`config/bhashini.conf`)

| Setting | Default | Meaning |
|---|---|---|
| `BHASHINI_API_KEY` | (required) | Dhruva inference key, sent as the raw `Authorization` header (no `Bearer`) |
| `BHASHINI_ASR_SERVICE_ID` / `_NMT_` / `_TTS_` | empty | Pin a model; empty lets Dhruva pick by language |
| `BHASHINI_ASR_SERVICE_ID_HI`, `BHASHINI_TTS_SERVICE_ID_TA`, … | empty | Per-language override |
| `BHASHINI_TTS_GENDER` | `female` | `female` or `male` |
| `BHASHINI_XLIT_SERVICE_ID` | `ai4bharat/indicxlit--cpu-fsv2` | Transliteration (required; Dhruva has no default) |
| `BHASHINI_ALD_SERVICE_ID` | `bhashini/iitmandi/audio-lang-detection/gpu` | Audio language detection |
| `BHASHINI_NER_SERVICE_ID` | `bhashini/ai4bharat/indic-ner` | NER |
| `BHASHINI_DENOISER_SERVICE_ID` | `bhashini/facebook/denoiser--gpu-t4` | Denoiser |
| `BHASHINI_OCR_SERVICE_ID` | `bhashini/bodhan/indic-doc/ocr` | OCR (much better than Dhruva's default on printed Hindi) |
| `BHASHINI_TLD_SERVICE_ID` | empty | Dhruva's default works |
| `BHASHINI_STREAM_URL` | `wss://dhruva-api.bhashini.gov.in` | Live ASR socket.io server |
| `BHASHINI_STREAM_ASR_SERVICE_ID` | empty | Pin the streaming ASR model |
| `ALLOWED_ORIGINS` | empty | CORS origins for the HTTP service, e.g. `http://localhost:3000` (restart to apply) |

Lookup order (later wins): defaults, legacy `.env`, environment variables, `config/bhashini.conf`.
The defaults were checked against the production Dhruva API on 2026-10-14.

## 3. Using it in your own UI

### Option A: keep the proxy as a separate service

```js
import { createBhashini, fileToWav } from './bhashini.js';   // copy web/bhashini.js + web/pcm-worklet.js
const bhashini = createBhashini({ baseUrl: 'http://localhost:8765' });  // add your origin to ALLOWED_ORIGINS
```

### Option B: add the endpoints to your existing backend

Copy `server/bhashini_client.py` and `server/config.py`, and call `transcribe`, `translate`,
`synthesize`, `speech_translate`, `transliterate`, `detect_language`, `detect_audio_language`,
`entities`, `ocr` and `denoise` from your own routes. They raise `BhashiniError(code, message, status)`.

### Browser API (`web/bhashini.js`)

```js
const bhashini = createBhashini();   // baseUrl '' = same origin

// Voice input. Must start from a click/tap. Stops automatically ~1.3 s after the user stops talking.
const text = await bhashini.recordAndTranscribe('hi');          // or 'auto' to detect the language

// Uploaded file (mp3, m4a, ogg, wav…) -> 16 kHz WAV -> text with segments
const wav = await fileToWav(input.files[0]);
const { text: t, segments, detected } = await bhashini.transcribeDetailed(wav, 'auto');
await bhashini.saveTranscript({ text: t, language: 'hi', title: 'SHG meeting', audioBase64: wav });

await bhashini.speak(botReply, 'hi');                            // TTS; bhashini.stop() interrupts
const english = await bhashini.translate('नमस्ते', 'hi', 'en');
const { transcript, translation, audio } = await bhashini.speechTranslate(wav, 'hi', 'en', { speak: true });
const { text: deva, suggestions } = await bhashini.transliterate('sunita', 'en', 'hi', { sentence: false });
const { language } = await bhashini.detectLanguage('ನಮಸ್ಕಾರ');   // 'kn'
const spoken = await bhashini.detectAudioLanguage(wav);          // { language: 'hi', score }
const { entities } = await bhashini.entities('सुनीता देवी पटना में रहती हैं', 'hi');
const { text: printed } = await bhashini.ocr({ imageBase64, language: 'hi' });
const clean = await bhashini.denoise(wav);                       // { audio_content, mime_type }
```

**Typical chatbot loop:**

```js
micButton.onclick = async () => {
  const userText = await bhashini.recordAndTranscribe(lang);
  showUserMessage(userText);
  const reply = await yourChatbot(userText);
  showBotMessage(reply);
  await bhashini.speak(reply, lang);
};
```

With Vite, put `pcm-worklet.js` in `public/` and pass `createBhashini({ workletUrl: '/pcm-worklet.js' })`.

### Live ASR (`web/stream/stream.js`)

```js
import { createLiveAsr } from './stream.js';
const live = createLiveAsr({ url: 'ws://localhost:8766/ws/asr', language: 'hi',
  onPartial: text => showDraft(text), onFinal: text => appendLine(text) });
await live.startMic();          // or live.streamFile(file) to replay a recording in real time
await live.stop();              // resolves after the last final text
const wav = live.recordingWav(); // what was sent, for saving
```

A pause of ~0.9 s finalises the current sentence, so a long session comes back as a list of lines.

## 4. HTTP API reference

| Endpoint | Request JSON | Response JSON |
|---|---|---|
| `asr` | `{audio_content, language}` (`language` may be `"auto"`) | `{text, language, duration, segments:[{start, text}], detected?}` |
| `tts` | `{text, language, gender?}` | `{language, segments:[{audio_content, mime_type}]}` |
| `translate` | `{text, source, target}` | `{text}` |
| `speech-translate` | `{audio_content, source, target, speak?, gender?}` | `{transcript, translation, audio?:{audio_content, mime_type}}` |
| `transliterate` | `{text, source, target, sentence?=true, suggestions?=5}` | `{text, suggestions:[…]}` |
| `detect-language` | `{text}` | `{language, script, score, candidates}` |
| `detect-audio-language` | `{audio_content}` | `{language, score, candidates}` |
| `ner` | `{text, language}` (Indic languages; not `en`) | `{entities:[{text, tag, start, end}]}` (`B-PER`, `B-LOC`, `B-ORG`, …) |
| `ocr` | `{image_content? (base64 PNG/JPEG), image_url? (https), language}` | `{text, language}` |
| `denoise` | `{audio_content}` | `{audio_content, mime_type}` |

All are `POST /api/bhashini/<endpoint>`. Audio in is base64 WAV, **mono, 16-bit, 16 kHz**
(`fileToWav` and the recorder produce this): 0.25 s to 10 min for `asr` (split at pauses into ≤30 s
pieces), up to 45 s for `speech-translate` and `denoise`. Text is up to 4000 characters.

**Saved transcripts:** `POST /api/transcripts {text, language, title?, source?, audio_content?}` →
entry; `GET /api/transcripts` → `{transcripts:[…]}`; `GET /api/transcripts/<id>.txt|.json|.wav`;
`DELETE /api/transcripts/<id>`.

**Settings:** `GET /api/settings` (key masked), `PUT /api/settings {NAME: value}` (empty key keeps the
current one), `POST /api/settings/test`. **Health:** `GET /healthz` on both services.

**Live ASR socket** (`/ws/asr` on port 8766): send `{"type":"start","language":"hi"}`, then binary
16 kHz mono int16 PCM frames, `{"type":"flush"}` to finalise a sentence and `{"type":"stop"}` to end.
You receive `ready`, `partial {text}`, `final {text}`, `error {message}` and `end`.

Errors return `{ "error": { "code": "...", "message": "..." } }` with status 422 (bad input),
502 (Bhashini rejected the request or returned bad data), 503 (not configured or unreachable)
or 504 (timeout).

## 5. Tests

```bash
docker compose --profile test run --rm test
```

This runs `tests/test_endpoints.py` against both running containers with real Bhashini calls:
health, settings (masking, write, validation, key test), every service above, validation errors,
transcript save/list/download/delete, and live ASR over the socket. Test speech is generated with TTS,
so no fixtures are needed. It also checks model selection. Last run: **26/26 passed**.

## 6. Raw Bhashini request (for porting to any language)

One endpoint handles most tasks:

```
POST https://dhruva-api.bhashini.gov.in/services/inference/pipeline
Authorization: <BHASHINI_API_KEY>
Content-Type: application/json
```

```jsonc
// ASR
{ "pipelineTasks": [{ "taskType": "asr", "config": {
    "language": { "sourceLanguage": "hi" }, "audioFormat": "wav", "samplingRate": 16000,
    "preProcessors": ["vad"], "postProcessors": ["itn"] } }],
  "inputData": { "audio": [{ "audioContent": "<base64 wav>" }] } }
// → pipelineResponse[0].output[0].source

// Translation → output[0].target            TTS → audio[0].audioContent (base64 WAV, 8 kHz)
// Transliteration: taskType "transliteration", config { language:{sourceLanguage, targetLanguage},
//   serviceId: "ai4bharat/indicxlit--cpu-fsv2", isSentence, numSuggestions } → output[0].target[]
// Text language: taskType "txt-lang-detection", inputData.input → output[0].langPrediction[]
// Audio language: taskType "audio-lang-detection", serviceId "bhashini/iitmandi/audio-lang-detection/gpu"
// NER: taskType "ner", serviceId "bhashini/ai4bharat/indic-ner" → output[0].nerPrediction[]
// OCR: taskType "ocr", inputData.image: [{ imageContent | imageUri }] → output[].source (words)
// Chains: several pipelineTasks in one request, e.g. asr + translation + tts.
```

The denoiser has its own endpoint, `POST …/services/inference/denoiser`, with body
`{ "config": { "serviceId": "bhashini/facebook/denoiser--gpu-t4" }, "audio": [{ "audioContent": "…" }] }`.
Send audio inline: Dhruva often fails to fetch `audioUri` links.

`vad` trims silence. `itn` turns spoken numbers into digits ("पांच सौ रुपये" → "₹500").
Retry only on network errors and 429/502/503/504; `bhashini_client.py` already does this.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Badge says "No API key" / `not_configured` (503) | Open Settings and save the key, or check `config/bhashini.conf` |
| `Bhashini rejected the API key` | Key revoked or expired. Get a new one from the Bhashini/ULCA dashboard |
| `language_unavailable` | Dhruva has no model for that language and task (e.g. NER in English), or a pinned service ID is wrong |
| Mic button does nothing / `NotAllowedError` | Page not on HTTPS/localhost, or mic permission denied |
| `invalid_audio` | Not 16 kHz mono WAV; use `fileToWav` or the recorder from `bhashini.js` |
| Live ASR: "Could not open the Bhashini stream" | Key invalid, or `BHASHINI_STREAM_URL` is unreachable from the container |
| Settings: `not_writable` | `config/` must be writable by uid 1000 in the container |
| CORS error | Add your UI origin to `ALLOWED_ORIGINS` and restart: `docker compose restart http` |
