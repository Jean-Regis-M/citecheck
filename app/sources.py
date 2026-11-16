"""Resolve a reference (URL, DOI, arXiv id, pasted text) into readable source text.

All network access goes through `safe_get`, which blocks private/loopback addresses (SSRF),
re-validates every redirect hop, and enforces a download size cap.
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from . import config

_UA = "CiteCheck/0.1 (student citation verifier)"
_DOI = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.I)
_ARXIV = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)


class SourceError(Exception):
    """A source could not be fetched or read. Message is safe to show to users."""


@dataclass
class SourceDoc:
    label: str
    title: str
    text: str
    scope: str  # "full_text" | "abstract_only" | "pasted_text"
    origin: str


def _is_public_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                or a.is_reserved or a.is_unspecified)


def validate_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SourceError("Only http(s) URLs are allowed.")
    if p.port not in (None, 80, 443):
        raise SourceError("Non-standard ports are not allowed.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise SourceError(f"Could not resolve host {p.hostname}.")
    for info in infos:
        if not _is_public_ip(info[4][0]):
            raise SourceError("URL points to a non-public address and was blocked.")
    return url


async def safe_get(client: httpx.AsyncClient, url: str, max_hops: int = 4) -> tuple[bytes, str]:
    """GET with SSRF checks on every hop and a streaming size cap. Returns (body, content_type)."""
    for _ in range(max_hops + 1):
        validate_url(url)
        try:
            async with client.stream("GET", url, headers={"User-Agent": _UA}, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise SourceError(f"Source returned HTTP {r.status_code}.")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > config.MAX_SOURCE_BYTES:
                        raise SourceError("Source is too large.")
                return bytes(buf), r.headers.get("content-type", "").lower()
        except httpx.HTTPError as e:
            raise SourceError(f"Network error fetching source: {type(e).__name__}.")
    raise SourceError("Too many redirects.")


def pdf_to_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:60]:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    except Exception:
        raise SourceError("Could not read the PDF.")


def html_to_text(data: bytes) -> tuple[str, str]:
    soup = BeautifulSoup(data, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        t.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    return title, soup.get_text(" ", strip=True)


async def _fetch_url(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    body, ctype = await safe_get(client, url)
    if "pdf" in ctype or body[:5] == b"%PDF-":
        return "", pdf_to_text(body)
    if "html" in ctype or "xml" in ctype or ctype.startswith("text/"):
        return html_to_text(body)
    raise SourceError(f"Unsupported content type: {ctype or 'unknown'}.")


def _inverted_to_text(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


async def _from_doi(client: httpx.AsyncClient, doi: str) -> tuple[str, str, str]:
    api = f"https://api.openalex.org/works/doi:{doi}"
    if config.CONTACT_EMAIL:
        api += f"?mailto={config.CONTACT_EMAIL}"
    body, _ = await safe_get(client, api)
    import json
    work = json.loads(body)
    title = work.get("title") or doi
    urls: list[str] = []
    best = work.get("best_oa_location") or {}
    for key in ("pdf_url", "landing_page_url"):
        if best.get(key):
            urls.append(best[key])
    if (work.get("open_access") or {}).get("oa_url"):
        urls.append(work["open_access"]["oa_url"])
    for u in dict.fromkeys(urls):
        try:
            _, text = await _fetch_url(client, u)
            if len(text.split()) > 300:
                return title, text, "full_text"
        except SourceError:
            continue
    abstract = _inverted_to_text(work.get("abstract_inverted_index"))
    if abstract:
        return title, abstract, "abstract_only"
    raise SourceError("No open-access full text or abstract found for this DOI. Paste the text instead.")


async def resolve_source(client: httpx.AsyncClient, label: str, kind: str, value: str) -> SourceDoc:
    value = value.strip()
    if not value:
        raise SourceError("Empty source.")
    if kind == "text":
        return SourceDoc(label, "Pasted text", value[:400_000], "pasted_text", "pasted")
    if kind == "auto":
        if value.lower().startswith(("http://", "https://")):
            kind = "url"
        elif _DOI.search(value):
            kind = "doi"
        elif _ARXIV.search(value):
            kind = "arxiv"
        else:
            kind = "text"
        if kind == "text":
            return SourceDoc(label, "Pasted text", value[:400_000], "pasted_text", "pasted")
    if kind == "arxiv":
        m = _ARXIV.search(value)
        if not m:
            raise SourceError("Could not read the arXiv id.")
        _, text = await _fetch_url(client, f"https://arxiv.org/pdf/{m.group(1)}")
        return SourceDoc(label, f"arXiv:{m.group(1)}", text, "full_text", f"arxiv:{m.group(1)}")
    if kind == "doi":
        m = _DOI.search(value)
        if not m:
            raise SourceError("Could not read the DOI.")
        doi = m.group(1).rstrip(".,;)")
        title, text, scope = await _from_doi(client, doi)
        return SourceDoc(label, title, text, scope, f"doi:{doi}")
    if kind == "url":
        # DOI/arXiv URLs get the better resolvers
        m = _ARXIV.search(value) if "arxiv.org" in value.lower() else None
        if m:
            return await resolve_source(client, label, "arxiv", value)
        if "doi.org/" in value.lower() and _DOI.search(value):
            return await resolve_source(client, label, "doi", value)
        title, text = await _fetch_url(client, value)
        return SourceDoc(label, title or value, text, "full_text", value)
    raise SourceError(f"Unknown source kind: {kind}")
