"""Chunking and BM25 passage retrieval (no external dependencies)."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the of in on at to for and or but is are was were be been by with as that this "
    "these those it its from which who whom than then so such not no can could may might "
    "will would should has have had do does did into over under between among their there".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def chunk_text(text: str, max_words: int = 120, overlap: int = 30) -> list[str]:
    """Split text into overlapping word windows, preferring sentence boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for s in sentences:
        n = len(s.split())
        if cur and cur_len + n > max_words:
            chunks.append(" ".join(cur))
            # carry over trailing sentences up to `overlap` words
            carry: list[str] = []
            carried = 0
            for prev in reversed(cur):
                w = len(prev.split())
                if carried + w > overlap:
                    break
                carry.insert(0, prev)
                carried += w
            cur, cur_len = carry, carried
        cur.append(s)
        cur_len += n
    if cur:
        chunks.append(" ".join(cur))
    return chunks


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tokens = [tokenize(d) for d in docs]
        self.tf = [Counter(t) for t in self.tokens]
        self.dl = [len(t) for t in self.tokens]
        self.avgdl = (sum(self.dl) / len(self.dl)) if docs else 0.0
        df: Counter[str] = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def top_k(self, query: str, k: int = 4) -> list[tuple[int, float]]:
        q = tokenize(query)
        scores: list[tuple[int, float]] = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w not in tf:
                    continue
                f = tf[w]
                denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                s += self.idf.get(w, 0.0) * f * (self.k1 + 1) / denom
            scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scores[:k] if s > 0]
