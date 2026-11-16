from __future__ import annotations

import os
from pathlib import Path

try:  # tiny .env loader so no extra dependency is needed
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
except OSError:
    pass


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MAX_SOURCE_BYTES = int(os.environ.get("MAX_SOURCE_BYTES", 15_000_000))
FETCH_TIMEOUT = float(os.environ.get("FETCH_TIMEOUT", 20))
MAX_CLAIMS = int(os.environ.get("MAX_CLAIMS", 25))
MAX_DRAFT_CHARS = int(os.environ.get("MAX_DRAFT_CHARS", 20_000))
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # optional, used for OpenAlex polite pool
