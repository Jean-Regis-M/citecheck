"""Evaluate CiteCheck's verifier on SciFact dev claims (Wadden et al., 2020).

Usage:
  python eval/run_scifact.py --data eval/data/scifact --n 60 --out eval/results/run1.json

Data: download data.tar.gz from the SciFact release and extract so that
  <data>/data/claims_dev.jsonl and <data>/data/corpus.jsonl exist.

Each claim is paired with ONE of its cited abstracts and judged by the real pipeline
(retrieval + Gemini + quote audit). Gold labels:
  SUPPORT -> supported, CONTRADICT -> contradicted, no evidence -> nei
Predictions are collapsed the same way: supported/partially_supported -> supported,
contradicted -> contradicted, not_supported/cannot_verify -> nei.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.llm import GeminiClient  # noqa: E402
from app.verify import build_index, verify_claim  # noqa: E402


def load(data: Path):
    base = data / "data" if (data / "data").exists() else data
    corpus = {}
    for line in (base / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        corpus[d["doc_id"]] = " ".join(d["abstract"])
    items = []
    for line in (base / "claims_dev.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        ev = c.get("evidence") or {}
        if ev:
            doc_id = int(next(iter(ev)))
            gold = "supported" if ev[str(doc_id)][0]["label"] == "SUPPORT" else "contradicted"
        elif c.get("cited_doc_ids"):
            doc_id, gold = int(c["cited_doc_ids"][0]), "nei"
        else:
            continue
        if doc_id in corpus:
            items.append({"id": c["id"], "claim": c["claim"], "doc_id": doc_id, "gold": gold})
    return corpus, items


def collapse(v: str) -> str:
    return {"supported": "supported", "partially_supported": "supported", "contradicted": "contradicted"}.get(v, "nei")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="eval/results/run.json")
    a = ap.parse_args()
    corpus, items = load(Path(a.data))
    random.Random(a.seed).shuffle(items)
    items = items[: a.n]
    rows = []
    sem = asyncio.Semaphore(2)
    async with httpx.AsyncClient() as http:
        llm = GeminiClient(http)
        if not llm.configured:
            sys.exit("Set GEMINI_API_KEY first.")

        async def one(it):
            async with sem:
                v = await verify_claim(llm, it["claim"], build_index(corpus[it["doc_id"]]), "full_text")
            return {**it, "raw_verdict": v.verdict, "pred": collapse(v.verdict), "quote": v.quote, "flags": v.flags}

        rows = await asyncio.gather(*(one(i) for i in items), return_exceptions=True)
    ok = [r for r in rows if isinstance(r, dict)]
    errs = len(rows) - len(ok)
    from collections import Counter as _C
    print('error types:', dict(_C(str(r)[:80] for r in rows if not isinstance(r, dict))))
    acc = sum(r["pred"] == r["gold"] for r in ok) / max(1, len(ok))
    pred_sup = [r for r in ok if r["pred"] == "supported"]
    prec_sup = sum(r["gold"] == "supported" for r in pred_sup) / max(1, len(pred_sup))
    confusion = Counter((r["gold"], r["pred"]) for r in ok)
    # Of claims truly unsupported by the source (nei+contradicted), how many were wrongly passed as supported?
    bad = [r for r in ok if r["gold"] != "supported"]
    false_pass = sum(r["pred"] == "supported" for r in bad) / max(1, len(bad))
    report = {
        "n_scored": len(ok), "n_errors": errs, "accuracy_3class": round(acc, 3),
        "precision_when_says_supported": round(prec_sup, 3),
        "false_pass_rate_on_unsupported_claims": round(false_pass, 3),
        "quote_withheld_count": sum("quote_not_found_in_source" in r["flags"] for r in ok),
        "confusion": {f"{g}->{p}": n for (g, p), n in sorted(confusion.items())},
        "model": llm.model,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"report": report, "rows": ok}, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
