"""Standalone Bhashini (Dhruva) client.

Speech:  transcribe (ASR), synthesize (TTS), detect_audio_language (ALD), denoise,
         speech_translate (ASR -> NMT -> optional TTS in one pipeline call)
Text:    translate (NMT), transliterate, detect_language (TLD), entities (NER)
Image:   ocr

No app dependencies beyond `requests`. Settings (API key, service IDs) come from config.py.
Never ship the key to a browser; call these functions from your server.
"""
import array
import base64
import binascii
import io
import re
import time
import wave

import requests

import config
import models

DHRUVA = 'https://dhruva-api.bhashini.gov.in/services/inference'
PIPELINE_URL = f'{DHRUVA}/pipeline'
ATTEMPTS = 3
RETRY_STATUS = {429, 502, 503, 504}
CHUNK = 900  # Max characters per model input; longer text is split.
RATE = 16000
SEGMENT_SECONDS = 30  # Long recordings are cut into pieces this size for ASR.
MAX_AUDIO_SECONDS = 600

LANGUAGES = {'en', 'hi', 'bn', 'ta', 'te', 'mr', 'gu', 'kn', 'ml', 'pa', 'or', 'as', 'ur', 'ne',
             'sa', 'bho', 'mai', 'doi', 'kok', 'ks', 'sd', 'brx', 'mni', 'sat', 'raj', 'mag', 'hne'}


class BhashiniError(Exception):
    def __init__(self, code, message, status=502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def env(name, default=None):
    return config.get(name, default)


def _key():
    key = env('BHASHINI_API_KEY')
    if not key:
        raise BhashiniError('not_configured', 'BHASHINI_API_KEY is not set. Add it on the Settings page.', 503)
    return key


def _post(url, payload, label, timeout):
    """POST to Dhruva, retrying only transient failures. Returns the parsed JSON body."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = requests.post(url, headers={'Authorization': _key()}, json=payload,
                                     timeout=timeout, allow_redirects=False)
        except requests.Timeout:
            raise BhashiniError(f'{label}_timeout', f'Bhashini {label} timed out.', 504) from None
        except requests.RequestException:
            if attempt == ATTEMPTS:
                raise BhashiniError('unavailable', 'Bhashini is unreachable.', 503) from None
        else:
            if response.status_code not in RETRY_STATUS or attempt == ATTEMPTS:
                break
        time.sleep(0.5 * attempt)
    if response.status_code in (400, 404, 422):
        raise BhashiniError('language_unavailable', f'Bhashini {label} does not support this language/service.')
    if response.status_code in (401, 403):
        raise BhashiniError('unauthorized', 'Bhashini rejected the API key.', 502)
    if not response.ok:
        raise BhashiniError('unavailable', f'Bhashini {label} failed (HTTP {response.status_code}).')
    try:
        return response.json()
    except ValueError:
        raise BhashiniError('invalid_response', f'Bhashini returned an unreadable {label} response.') from None


def _run(tasks, input_data, timeout):
    """Run a pipeline of [(taskType, config), ...]. Returns {taskType: stage}."""
    payload = {'pipelineTasks': [{'taskType': t, 'config': c} for t, c in tasks], 'inputData': input_data}
    label = '+'.join(t for t, _ in tasks)
    body = _post(PIPELINE_URL, payload, label, timeout)
    try:
        stages = {s['taskType']: s for s in body['pipelineResponse']}
        if not all(t in stages for t, _ in tasks):
            raise KeyError()
        return stages
    except (KeyError, TypeError):
        raise BhashiniError('invalid_response', f'Bhashini returned an incomplete {label} response.') from None


def _pipeline(task, config_, input_data, timeout):
    return _run([(task, config_)], input_data, timeout)[task]


def _chunks(text):
    text, out = text.strip(), []
    while len(text) > CHUNK:
        end = max(text.rfind('\n', 0, CHUNK), text.rfind(' ', 0, CHUNK))
        end = end if end >= CHUNK // 2 else CHUNK
        out.append(text[:end])
        text = text[end:].lstrip()
    return out + ([text] if text else [])


def _check_language(*codes):
    for code in codes:
        if code not in LANGUAGES:
            raise BhashiniError('invalid_language', f'Unsupported language code: {code!r}.', 422)


def _check_text(text, limit=4000):
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        raise BhashiniError('invalid_text', f'Send 1-{limit} characters of text.', 422)


def _service(prefix, language=''):
    """Per-language service ID, falling back to the generic one; empty lets Dhruva choose."""
    generic = env(f'BHASHINI_{prefix}_SERVICE_ID')
    return env(f'BHASHINI_{prefix}_SERVICE_ID_{language.upper()}', generic) if language else generic


def _model(task, prefix, source='', target=None, chosen=None):
    """Service ID to use: the caller's choice (must be in models.py), else the configured one,
    else empty (Dhruva picks). A configured model that can't handle the language is swapped for
    the first catalog model that can, so e.g. NER in English still works."""
    if chosen:
        model = models.find(task, chosen)
        if not model:
            raise BhashiniError('invalid_model', f'Unknown {task} model: {chosen!r}.', 422)
        if not models.supports(model, source or None, target):
            raise BhashiniError('invalid_model', f'{chosen} does not support this language.', 422)
        return chosen
    service = _service(prefix, source if source else '')
    model = models.find(task, service)
    if model and not models.supports(model, source or None, target):
        return models.first_for(task, source or None, target) or service
    return service


def _with_service(config_, service):
    if service:
        config_['serviceId'] = service
    return config_


# --- audio helpers -------------------------------------------------------------------------

def _pcm(audio_base64, max_seconds=MAX_AUDIO_SECONDS):
    """Validate base64 WAV (mono, 16-bit, 16 kHz) and return its raw PCM bytes."""
    try:
        raw = base64.b64decode(audio_base64, validate=True)
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, RATE):
                raise ValueError()
            frames = audio.readframes(audio.getnframes())
    except (ValueError, TypeError, binascii.Error, wave.Error, EOFError):
        raise BhashiniError('invalid_audio', 'Send mono 16 kHz 16-bit WAV.', 422) from None
    if not RATE // 4 <= len(frames) // 2 <= max_seconds * RATE:
        raise BhashiniError('invalid_audio', f'Audio must be 0.25-{max_seconds} s long.', 422)
    return frames


def _wav_base64(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return base64.b64encode(buffer.getvalue()).decode()


def _segments(pcm):
    """Cut PCM into <=30 s pieces, ending each at the quietest 100 ms of its last 5 s."""
    samples = array.array('h', pcm)
    size, window, out, start = SEGMENT_SECONDS * RATE, RATE // 10, [], 0
    while len(samples) - start > size:
        best, quietest = start + size, None
        for at in range(start + size - 5 * RATE, start + size - window, window):
            energy = sum(abs(v) for v in samples[at:at + window:8])
            if quietest is None or energy < quietest:
                best, quietest = at + window // 2, energy
        out.append(samples[start:best].tobytes())
        start = best
    tail = samples[start:].tobytes()
    if len(tail) >= RATE // 2 or not out:  # Drop a sub-quarter-second tail; ASR rejects it.
        out.append(tail)
    return out


def _mime(raw):
    if raw.startswith(b'RIFF') and raw[8:12] == b'WAVE':
        return 'audio/wav'
    if raw.startswith(b'fLaC'):
        return 'audio/flac'
    if raw.startswith(b'OggS'):
        return 'audio/ogg'
    if raw.startswith(b'ID3') or raw[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        return 'audio/mpeg'
    raise BhashiniError('invalid_response', 'Bhashini returned unsupported audio.')


def _audio_out(encoded):
    try:
        return {'audio_content': encoded, 'mime_type': _mime(base64.b64decode(encoded, validate=True))}
    except (TypeError, binascii.Error):
        raise BhashiniError('invalid_response', 'Bhashini returned incomplete audio.') from None


def _asr_config(language, service_id=None):
    # vad trims silence; itn turns spoken numbers into digits ("एक दो" -> "1 2").
    return _with_service({'language': {'sourceLanguage': language}, 'audioFormat': 'wav', 'samplingRate': RATE,
                          'preProcessors': ['vad'], 'postProcessors': ['itn']},
                         _model('asr', 'ASR', language, chosen=service_id))


def _tts_config(language, gender, service_id=None):
    return {'language': {'sourceLanguage': language}, 'serviceId': _model('tts', 'TTS', language, chosen=service_id),
            'gender': gender or env('BHASHINI_TTS_GENDER'), 'samplingRate': 8000}


# --- speech ----------------------------------------------------------------------------------

def detect_audio_language(audio_base64, service_id=None):
    """Spoken language of base64 16 kHz WAV (first 30 s). Returns {language, score, candidates}."""
    pcm = _pcm(audio_base64)[:SEGMENT_SECONDS * RATE * 2]
    config_ = _with_service({}, _model('audio-lang-detection', 'ALD', chosen=service_id))
    stage = _pipeline('audio-lang-detection', config_, {'audio': [{'audioContent': _wav_base64(pcm)}]}, 30)
    try:
        predictions = stage['output'][0]['langPrediction']
        candidates = [{'language': p['langCode'], 'score': p.get('langScore')} for p in predictions]
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete language detection.') from None
    if not candidates:
        raise BhashiniError('speech_empty', 'Could not tell which language was spoken.', 422)
    return {**candidates[0], 'candidates': candidates}


def transcribe(audio_base64, language, service_id=None):
    """Speech -> text. Base64 WAV, mono, 16-bit PCM, 16 kHz, 0.25 s-10 min.

    language='auto' runs audio language detection first. Recordings over 30 s are split at
    pauses and transcribed piece by piece; `segments` lists each piece's text and start time.
    """
    pcm = _pcm(audio_base64)
    detected = None
    if language == 'auto':
        detected = detect_audio_language(audio_base64)
        language = detected['language']
        if service_id and not models.supports(models.find('asr', service_id) or {'languages': []}, language):
            service_id = None  # The picked model can't do the detected language; let the default handle it.
    _check_language(language)
    pieces, offset = [], 0
    for segment in _segments(pcm):
        stage = _pipeline('asr', _asr_config(language, service_id), {'audio': [{'audioContent': _wav_base64(segment)}]}, 60)
        text = ' '.join(str(o.get('source', '')).strip() for o in stage.get('output') or []).strip()
        if text:
            pieces.append({'start': round(offset / 2 / RATE, 2), 'text': text})
        offset += len(segment)
    if not pieces:
        raise BhashiniError('speech_empty', 'No speech was detected.', 422)
    result = {'text': ' '.join(p['text'] for p in pieces), 'language': language,
              'duration': round(len(pcm) / 2 / RATE, 2), 'segments': pieces}
    if detected:
        result['detected'] = detected
    return result


def _speakable(text):
    """Strip markdown so the voice doesn't read out symbols or URLs."""
    text = re.sub(r'```[\s\S]*?```', ' ', text)
    text = re.sub(r'!?\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'(?m)^\s*[#>*-]+\s*', '', text)
    return re.sub(r'[*_`]', '', text).strip()


def synthesize(text, language, gender=None, service_id=None):
    """Text -> speech. Returns ordered base64 audio segments (one per ~900-char chunk)."""
    _check_language(language)
    if not isinstance(text, str) or len(text) > 4000:
        raise BhashiniError('invalid_text', 'Send up to 4000 characters of text.', 422)
    chunks = _chunks(_speakable(text))
    if not chunks:
        raise BhashiniError('speech_empty', 'This text has nothing readable.', 422)
    segments = []
    for chunk in chunks:
        stage = _pipeline('tts', _tts_config(language, gender, service_id), {'input': [{'source': chunk}]}, 30)
        try:
            segments.append(_audio_out(stage['audio'][0]['audioContent']))
        except (KeyError, IndexError, TypeError):
            raise BhashiniError('invalid_response', 'Bhashini returned incomplete audio.') from None
    return {'language': language, 'segments': segments}


def speech_translate(audio_base64, source, target, speak=False, gender=None, asr_service_id=None,
                     nmt_service_id=None, tts_service_id=None):
    """Speech in one language -> text (and optionally speech) in another, in one Dhruva call.

    Mirrors the collection's "ASR+NMT" and "ASR+NMT+TTS" compute requests. Max 45 s of audio.
    """
    _check_language(source, target)
    pcm = _pcm(audio_base64, max_seconds=45)
    tasks = [('asr', _asr_config(source, asr_service_id)),
             ('translation', _with_service({'language': {'sourceLanguage': source, 'targetLanguage': target}},
                                           _model('translation', 'NMT', source, target, nmt_service_id)))]
    if speak:
        tasks.append(('tts', _tts_config(target, gender, tts_service_id)))
    stages = _run(tasks, {'audio': [{'audioContent': _wav_base64(pcm)}]}, 90)
    try:
        transcript = ' '.join(str(o.get('source', '')).strip() for o in stages['asr']['output'] or []).strip()
        translation = ' '.join(str(o.get('target', '')).strip() for o in stages['translation']['output'] or []).strip()
        result = {'transcript': transcript, 'translation': translation, 'source': source, 'target': target}
        if speak:
            result['audio'] = _audio_out(stages['tts']['audio'][0]['audioContent'])
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete speech translation.') from None
    if not transcript:
        raise BhashiniError('speech_empty', 'No speech was detected.', 422)
    return result


def denoise(audio_base64, service_id=None):
    """Remove background noise from base64 16 kHz WAV (max 45 s). Returns cleaned audio."""
    pcm = _pcm(audio_base64, max_seconds=45)
    payload = {'config': _with_service({}, _model('denoiser', 'DENOISER', chosen=service_id)), 'audio': [{'audioContent': _wav_base64(pcm)}]}
    body = _post(f'{DHRUVA}/denoiser', payload, 'denoiser', 60)
    try:
        return _audio_out(body['audio'][0]['audioContent'])
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned incomplete denoised audio.') from None


# --- text ------------------------------------------------------------------------------------

def translate(text, source, target, service_id=None):
    """Text -> text between two language codes, e.g. translate('Hello', 'en', 'hi')."""
    _check_language(source, target)
    _check_text(text)
    if source == target:
        return {'text': text}
    chunks = _chunks(text)
    config_ = {'language': {'sourceLanguage': source, 'targetLanguage': target},
               'serviceId': _model('translation', 'NMT', source, target, service_id)}
    stage = _pipeline('translation', config_, {'input': [{'source': c} for c in chunks]}, 30)
    outputs = stage.get('output') or []
    if len(outputs) != len(chunks) or any(not str(o.get('target', '')).strip() for o in outputs):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete translation.')
    return {'text': '\n'.join(o['target'].strip() for o in outputs)}


def transliterate(text, source, target, sentence=True, suggestions=5, service_id=None):
    """Same words, other script: 'namaste' (en) -> 'नमस्ते' (hi), or back.

    sentence=True converts the whole text; sentence=False returns up to `suggestions`
    candidates for a single word (for type-ahead keyboards).
    """
    _check_language(source, target)
    _check_text(text, 1000)
    config_ = _with_service({'language': {'sourceLanguage': source, 'targetLanguage': target},
                             'isSentence': bool(sentence)},
                            _model('transliteration', 'XLIT', source, target, service_id))
    if not sentence:
        config_['numSuggestions'] = max(1, min(int(suggestions), 10))
    stage = _pipeline('transliteration', config_, {'input': [{'source': text.strip()}]}, 20)
    try:
        options = [str(t) for t in stage['output'][0]['target'] if str(t).strip()]
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete transliteration.') from None
    if not options:
        raise BhashiniError('invalid_response', 'Bhashini returned no transliteration.')
    return {'text': options[0], 'suggestions': options}


def detect_language(text, service_id=None):
    """Language of a piece of text. Returns {language, script, score, candidates}."""
    _check_text(text, 1000)
    stage = _pipeline('txt-lang-detection', _with_service({}, _model('txt-lang-detection', 'TLD', chosen=service_id)), {'input': [{'source': text.strip()}]}, 20)
    try:
        candidates = [{'language': p['langCode'], 'script': p.get('scriptCode'), 'score': p.get('langScore')}
                      for p in stage['output'][0]['langPrediction']]
        return {**candidates[0], 'candidates': candidates}
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete language detection.') from None


def entities(text, language, service_id=None):
    """Named entities (people, places, organisations) in Indic-language text."""
    _check_language(language)
    _check_text(text)
    config_ = _with_service({'language': {'sourceLanguage': language}}, _model('ner', 'NER', language, chosen=service_id))
    stage = _pipeline('ner', config_, {'input': [{'source': text.strip()}]}, 20)
    try:
        found = stage['output'][0].get('nerPrediction') or []
        return {'entities': [{'text': e['token'], 'tag': e['tag'], 'start': e.get('tokenStartIndex'),
                              'end': e.get('tokenEndIndex')} for e in found]}
    except (KeyError, IndexError, TypeError):
        raise BhashiniError('invalid_response', 'Bhashini returned an incomplete NER response.') from None


# --- image -----------------------------------------------------------------------------------

def ocr(language, image_base64=None, image_url=None, service_id=None):
    """Printed text in an image (photo of a register, form, notice). Give base64 or a public URL."""
    _check_language(language)
    if image_base64:
        try:
            raw = base64.b64decode(image_base64, validate=True)
        except (TypeError, binascii.Error):
            raise BhashiniError('invalid_image', 'Image must be base64.', 422) from None
        if not (raw.startswith(b'\x89PNG') or raw.startswith(b'\xff\xd8')):
            raise BhashiniError('invalid_image', 'Send a PNG or JPEG image.', 422)
        image = {'imageContent': image_base64}
    elif image_url and re.match(r'^https://', image_url):
        image = {'imageUri': image_url}
    else:
        raise BhashiniError('invalid_image', 'Send image_content (base64) or an https image_url.', 422)
    config_ = _with_service({'language': {'sourceLanguage': language}}, _model('ocr', 'OCR', language, chosen=service_id))
    stage = _pipeline('ocr', config_, {'image': [image]}, 90)
    words = [str(o.get('source', '')).strip() for o in stage.get('output') or []]
    text = ' '.join(w for w in words if w)
    if not text:
        raise BhashiniError('text_empty', 'No text was found in the image.', 422)
    return {'text': text, 'language': language}
