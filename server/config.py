"""Settings for the kit, kept in one KEY=VALUE conf file.

Lookup order (later wins): built-in defaults, a legacy `.env` next to the kit, real environment
variables, then `config/bhashini.conf`. The conf file wins so the Settings page (which writes it)
takes effect immediately without restarting containers. The file is re-read when it changes.
"""
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF_PATH = Path(os.environ.get('BHASHINI_CONF', ROOT / 'config' / 'bhashini.conf'))

# Every setting the kit understands, with its default. Empty service IDs let Dhruva pick a model.
DEFAULTS = {
    'BHASHINI_API_KEY': '',
    'BHASHINI_ASR_SERVICE_ID': '',
    'BHASHINI_NMT_SERVICE_ID': '',
    'BHASHINI_TTS_SERVICE_ID': '',
    'BHASHINI_TTS_GENDER': 'female',
    'BHASHINI_XLIT_SERVICE_ID': 'ai4bharat/indicxlit--cpu-fsv2',
    'BHASHINI_TLD_SERVICE_ID': '',
    'BHASHINI_ALD_SERVICE_ID': 'bhashini/iitmandi/audio-lang-detection/gpu',
    'BHASHINI_NER_SERVICE_ID': 'bhashini/ai4bharat/indic-ner',
    'BHASHINI_OCR_SERVICE_ID': 'bhashini/bodhan/indic-doc/ocr',
    'BHASHINI_DENOISER_SERVICE_ID': 'bhashini/facebook/denoiser--gpu-t4',
    'BHASHINI_STREAM_URL': 'wss://dhruva-api.bhashini.gov.in',
    'BHASHINI_STREAM_ASR_SERVICE_ID': '',
    'ALLOWED_ORIGINS': '',
}
SECRET = 'BHASHINI_API_KEY'

# Hosted mode (Vercel sets VERCEL=1): read-only filesystem, no sockets. The key and the access code
# come from the host's environment variables; settings writes and saved transcripts are disabled.
HOSTED = bool(os.environ.get('VERCEL') or os.environ.get('BHASHINI_HOSTED'))
# Optional shared code the browser must send as X-Access-Code on every /api call.
ACCESS_CODE = os.environ.get('BHASHINI_ACCESS_CODE', '')
_VALUE = re.compile(r'^[^\r\n]*$')
_lock = threading.Lock()
_cache = {'mtime': None, 'values': {}}


def _parse(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                name, value = line.split('=', 1)
                values[name.strip()] = value.strip()
    return values


_dotenv = _parse(ROOT / '.env')


def _conf():
    try:
        mtime = CONF_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    with _lock:
        if _cache['mtime'] != mtime:
            _cache['values'], _cache['mtime'] = _parse(CONF_PATH), mtime
        return _cache['values']


def get(name, default=None):
    """Current value of a setting. Per-language keys like BHASHINI_TTS_SERVICE_ID_TA also work."""
    for source in (_conf(), os.environ, _dotenv):
        if source.get(name):
            return source[name]
    return DEFAULTS.get(name, '') if default is None else default


def snapshot():
    """All known settings with the API key masked, for the Settings page."""
    values = {name: get(name) for name in DEFAULTS}
    key = values[SECRET]
    values[SECRET] = f'{key[:4]}…{key[-4:]}' if len(key) > 12 else ('set' if key else '')
    return {'values': values, 'key_set': bool(key), 'path': str(CONF_PATH)}


def save(updates):
    """Merge updates into the conf file. An empty API key in `updates` keeps the current one."""
    for name, value in updates.items():
        if name not in DEFAULTS and not re.fullmatch(r'BHASHINI_(ASR|NMT|TTS)_SERVICE_ID_[A-Z]{2,3}', name):
            raise ValueError(f'Unknown setting {name}.')
        if not isinstance(value, str) or not _VALUE.match(value):
            raise ValueError(f'{name} must be a single line of text.')
    with _lock:
        current = _parse(CONF_PATH)
        for name, value in updates.items():
            if name == SECRET and not value.strip():
                continue
            current[name] = value.strip()
        lines = ['# Bhashini kit settings. Written by the Settings page; safe to edit by hand.',
                 '# Never commit this file: it holds the API key.']
        lines += [f'{name}={current[name]}' for name in sorted(current, key=lambda n: (n not in DEFAULTS, n))]
        CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONF_PATH.with_suffix('.tmp')
        tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONF_PATH)
        _cache['mtime'] = None
