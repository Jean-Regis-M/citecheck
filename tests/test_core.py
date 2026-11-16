import pytest

from app.extract import extract_claims
from app.retrieve import BM25, chunk_text
from app.sources import SourceError, validate_url, _is_public_ip
from app.verify import Evidence, audit, quote_in_passage


def test_extract_numeric_and_ranges():
    d = "Sleep loss harms memory [1]. Exercise helps mood [2,3]. Unrelated sentence. Both matter [1-2]."
    c = extract_claims(d)
    assert [x.labels for x in c] == [["1"], ["2", "3"], ["1", "2"]]
    assert c[0].sentence == "Sleep loss harms memory."


def test_extract_labelled():
    c = extract_claims("Transformers scale well [vaswani2017].")
    assert c[0].labels == ["vaswani2017"]


def test_bm25_ranks_relevant_first():
    docs = ["Cats purr when content.", "Mitochondria produce ATP in cells.", "The stock market fell."]
    top = BM25(docs).top_k("which organelle produces ATP", 1)
    assert top[0][0] == 1


def test_chunking_covers_text():
    text = " ".join(f"Sentence number {i} is here." for i in range(200))
    chunks = chunk_text(text, max_words=50, overlap=10)
    assert len(chunks) > 5 and all(len(c.split()) <= 70 for c in chunks)


def test_quote_matching_tolerates_pdf_artifacts():
    assert quote_in_passage("results were signifi-\ncant at p < 0.05", "The results were significant at p<0.05 overall.")
    assert not quote_in_passage("invented evidence sentence here", "The results were significant at p<0.05 overall.")


def test_audit_withholds_fabricated_quote():
    passages = [Evidence(1, "Aspirin reduced fever in the treated group.", 3.0)]
    raw = {"verdict": "supported", "passage": 1, "quote": "Aspirin cures cancer completely", "confidence": 0.9}
    v = audit(raw, passages, "full_text")
    assert v.verdict == "cannot_verify" and "quote_not_found_in_source" in v.flags


def test_audit_keeps_valid_quote():
    passages = [Evidence(1, "Aspirin reduced fever in the treated group.", 3.0)]
    raw = {"verdict": "supported", "passage": 1, "quote": "Aspirin reduced fever", "confidence": 0.9}
    assert audit(raw, passages, "full_text").verdict == "supported"


def test_abstract_only_never_claims_not_supported():
    raw = {"verdict": "not_supported", "passage": 0, "quote": "", "confidence": 0.8}
    assert audit(raw, [Evidence(1, "x y z", 1)], "abstract_only").verdict == "cannot_verify"


def test_ssrf_blocking():
    for bad in ["http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data/",
                "file:///etc/passwd", "http://10.0.0.1/", "http://example.com:8080/"]:
        with pytest.raises(SourceError):
            validate_url(bad)
    assert not _is_public_ip("192.168.1.1") and _is_public_ip("8.8.8.8")


def test_rate_limit_blocks_after_limit(monkeypatch):
    from fastapi import HTTPException
    from app import main
    main._hits.clear()
    monkeypatch.setattr(main, "RATE_LIMIT", 2)
    main.rate_limit("1.2.3.4"); main.rate_limit("1.2.3.4")
    with pytest.raises(HTTPException) as e:
        main.rate_limit("1.2.3.4")
    assert e.value.status_code == 429
    main.rate_limit("5.6.7.8")  # other visitors unaffected


def test_llm_cache_key_is_deterministic_and_input_sensitive():
    from app import llm
    k = llm._cache_path("m", "s", "u", {"a": 1})
    assert k == llm._cache_path("m", "s", "u", {"a": 1})
    assert k != llm._cache_path("m", "s", "u2", {"a": 1})
    assert k != llm._cache_path("m2", "s", "u", {"a": 1})
