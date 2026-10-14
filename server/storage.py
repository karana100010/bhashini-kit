"""Saved transcripts: one JSON file (+ optional WAV) per entry under data/transcripts/."""
import base64
import binascii
import json
import os
import re
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = Path(os.environ.get('BHASHINI_DATA', ROOT / 'data')) / 'transcripts'
_ID = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{6}$')


class StorageError(Exception):
    pass


def save(text, language, source='asr', audio_base64=None, title=''):
    if not isinstance(text, str) or not text.strip():
        raise StorageError('Nothing to save.')
    entry_id = time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
    DIR.mkdir(parents=True, exist_ok=True)
    entry = {'id': entry_id, 'title': (title or '').strip()[:120], 'text': text.strip(), 'language': language,
             'source': source, 'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'has_audio': False}
    if audio_base64:
        try:
            raw = base64.b64decode(audio_base64, validate=True)
        except (TypeError, binascii.Error):
            raise StorageError('Audio must be base64 WAV.') from None
        if not (raw.startswith(b'RIFF') and raw[8:12] == b'WAVE'):
            raise StorageError('Audio must be WAV.')
        (DIR / f'{entry_id}.wav').write_bytes(raw)
        entry['has_audio'] = True
    (DIR / f'{entry_id}.json').write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding='utf-8')
    return entry


def listing(limit=200):
    if not DIR.exists():
        return []
    entries = []
    for path in sorted(DIR.glob('*.json'), reverse=True)[:limit]:
        try:
            entries.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return entries


def path(entry_id, ext):
    """File for an entry, or None. ext is 'json' or 'wav'."""
    if not _ID.match(entry_id) or ext not in ('json', 'wav'):
        return None
    file = DIR / f'{entry_id}.{ext}'
    return file if file.exists() else None


def delete(entry_id):
    if not _ID.match(entry_id):
        return False
    found = False
    for ext in ('json', 'wav'):
        file = DIR / f'{entry_id}.{ext}'
        if file.exists():
            file.unlink()
            found = True
    return found
