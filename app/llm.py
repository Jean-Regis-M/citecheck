"""Minimal Gemini REST client with JSON-schema constrained output and retries."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from . import config


class LLMError(Exception):
    pass


_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _cache_path(model: str, system: str, user: str, schema: dict) -> Path:
    h = hashlib.sha256(json.dumps([model, system, user, schema], sort_keys=True).encode()).hexdigest()
    return _CACHE_DIR / f"{h}.json"


class GeminiClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None, model: str | None = None):
        self.client = client
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def generate_json(self, system: str, user: str, schema: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        if not self.configured:
            raise LLMError("GEMINI_API_KEY is not set.")
        cp = _cache_path(self.model, system, user, schema)
        try:
            if cp.exists():
                return json.loads(cp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        last = "unknown error"
        for attempt in range(retries):
            try:
                r = await self.client.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=60)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    await asyncio.sleep(2 ** attempt + 1)
                    continue
                if r.status_code >= 400:
                    raise LLMError(f"Gemini returned HTTP {r.status_code}.")
                data = r.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                result = json.loads(text)
                try:
                    _CACHE_DIR.mkdir(exist_ok=True)
                    cp.write_text(json.dumps(result), encoding="utf-8")
                except OSError:
                    pass
                return result
            except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
                last = type(e).__name__
                await asyncio.sleep(1 + attempt)
        raise LLMError(f"Gemini request failed after {retries} attempts ({last}).")
