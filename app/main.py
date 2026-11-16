from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .llm import GeminiClient
from .pipeline import SourceInput, check_draft

WEB = Path(__file__).resolve().parent.parent / "web"


class SourceIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=400_000)
    kind: str = Field(default="auto", pattern="^(auto|url|doi|arxiv|text)$")


class CheckIn(BaseModel):
    draft: str = Field(min_length=10, max_length=config.MAX_DRAFT_CHARS)
    sources: list[SourceIn] = Field(min_length=1, max_length=20)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=config.FETCH_TIMEOUT)
    app.state.llm = GeminiClient(app.state.http)
    yield
    await app.state.http.aclose()


RATE_LIMIT = int(config.os.environ.get("RATE_LIMIT_PER_HOUR", 10))
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(ip: str) -> None:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, f"Limit of {RATE_LIMIT} checks per hour reached. Please try again later.")
    q.append(now)


app = FastAPI(title="CiteCheck", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"ok": True, "llm_configured": app.state.llm.configured, "model": app.state.llm.model}


@app.post("/api/check")
async def check(body: CheckIn, request: Request):
    if not app.state.llm.configured:
        raise HTTPException(503, "The server has no GEMINI_API_KEY configured.")
    rate_limit(request.client.host if request.client else "unknown")
    srcs = [SourceInput(s.label, s.value, s.kind) for s in body.sources]
    return await check_draft(body.draft, srcs, app.state.http, app.state.llm)


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
