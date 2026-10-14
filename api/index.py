"""Vercel entry point: the HTTP proxy + UI from server/app.py as one Python function.

Vercel sets VERCEL=1, which switches the app to hosted mode (see server/config.py). Set
BHASHINI_API_KEY and BHASHINI_ACCESS_CODE as Vercel environment variables.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))

from app import app  # noqa: E402,F401
