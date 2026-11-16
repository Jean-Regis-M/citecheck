from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field

import httpx

from . import config
from .extract import extract_claims
from .llm import GeminiClient, LLMError
from .sources import SourceDoc, SourceError, resolve_source
from .verify import Verdict, build_index, verify_claim


@dataclass
class SourceInput:
    label: str
    value: str
    kind: str = "auto"


@dataclass
class ClaimResult:
    index: int
    claim: str
    label: str
    source_title: str = ""
    source_scope: str = ""
    verdict: str = "cannot_verify"
    quote: str = ""
    issue: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    error: str = ""


async def check_draft(draft: str, sources: list[SourceInput], http: httpx.AsyncClient, llm: GeminiClient) -> dict:
    claims = extract_claims(draft)[: config.MAX_CLAIMS]
    by_label = {s.label.strip(): s for s in sources}

    docs: dict[str, SourceDoc | str] = {}

    async def load(s: SourceInput) -> None:
        try:
            docs[s.label.strip()] = await resolve_source(http, s.label.strip(), s.kind, s.value)
        except SourceError as e:
            docs[s.label.strip()] = str(e)

    needed = {lab for c in claims for lab in c.labels if lab in by_label}
    await asyncio.gather(*(load(by_label[lab]) for lab in needed))

    indexes = {lab: build_index(d.text) for lab, d in docs.items() if isinstance(d, SourceDoc)}
    sem = asyncio.Semaphore(3)
    results: list[ClaimResult] = []

    async def run(claim, label: str) -> ClaimResult:
        r = ClaimResult(claim.index, claim.sentence, label)
        d = docs.get(label)
        if label not in by_label:
            r.error = f"No source was provided for citation [{label}]."
            r.flags.append("missing_source")
            return r
        if isinstance(d, str):
            r.error = d
            r.flags.append("source_unavailable")
            return r
        r.source_title, r.source_scope = d.title, d.scope
        try:
            async with sem:
                v: Verdict = await verify_claim(llm, claim.sentence, indexes[label], d.scope)
        except LLMError as e:
            r.error = str(e)
            r.flags.append("llm_error")
            return r
        r.verdict, r.quote, r.issue, r.reasoning = v.verdict, v.quote, v.issue, v.reasoning
        r.confidence, r.flags = v.confidence, v.flags
        r.passages = [asdict(p) for p in v.passages]
        return r

    tasks = [run(c, lab) for c in claims for lab in c.labels]
    results = await asyncio.gather(*tasks)

    summary: dict[str, int] = {}
    for r in results:
        key = "error" if r.error else r.verdict
        summary[key] = summary.get(key, 0) + 1
    return {
        "claims_found": len(claims),
        "checks": len(results),
        "summary": summary,
        "results": [asdict(r) for r in results],
        "truncated": len(extract_claims(draft)) > config.MAX_CLAIMS,
    }
