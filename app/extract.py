"""Deterministic extraction of cited claims from a draft.

Supports numeric markers such as [1], [2,3], [1-3] and labelled markers such as [smith2020].
Doing this without an LLM keeps the claim boundaries auditable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_MARKER = re.compile(r"\[([A-Za-z0-9_\-]+(?:\s*[,;–\-]\s*[A-Za-z0-9_\-]+)*)\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass
class CitedClaim:
    index: int
    sentence: str  # sentence with markers removed
    original: str  # sentence as written
    labels: list[str]


def _expand(token: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,;]", token) if p.strip()]
    out: list[str] = []
    for p in parts:
        m = re.fullmatch(r"(\d+)\s*[–\-]\s*(\d+)", p)
        if m and int(m.group(2)) >= int(m.group(1)) and int(m.group(2)) - int(m.group(1)) < 50:
            out.extend(str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1))
        else:
            out.append(p)
    return out


def extract_claims(draft: str) -> list[CitedClaim]:
    draft = re.sub(r"\s+", " ", draft).strip()
    claims: list[CitedClaim] = []
    for sent in _SENT_SPLIT.split(draft):
        labels: list[str] = []
        for m in _MARKER.finditer(sent):
            labels.extend(_expand(m.group(1)))
        if not labels:
            continue
        clean = re.sub(r"\s+", " ", _MARKER.sub("", sent)).strip()
        clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
        seen: set[str] = set()
        uniq = [x for x in labels if not (x in seen or seen.add(x))]
        claims.append(CitedClaim(len(claims), clean, sent, uniq))
    return claims
