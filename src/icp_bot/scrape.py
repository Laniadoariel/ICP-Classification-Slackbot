from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36"
)


@dataclass(frozen=True)
class ScrapeResult:
    base_url: str
    combined_text: str
    attempted: List[Tuple[str, str]]


class ScrapeError(RuntimeError):
    def __init__(self, kind: str, attempted: List[Tuple[str, str]]):
        super().__init__(kind)
        self.kind = kind
        self.attempted = attempted


def _fetch_html(url: str, timeout_s: float = 15) -> tuple[Optional[str], str]:
    """
    Returns (html, status_key).
    status_key is a stable, non-technical string for user-friendly reporting.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout_s,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None, "connect_failed"

    code = resp.status_code
    if code == 404:
        return None, "not_found"
    if code in (401, 403):
        return None, "blocked"
    if code >= 400:
        return None, "http_error"

    return resp.text, "ok"


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Try to minimize boilerplate so the LLM sees the "main" content.
    for tag in soup(["nav", "footer", "header", "aside"]):
        tag.decompose()

    parts: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if len(txt) < 3:
            continue
        parts.append(txt)

    # De-dupe exact repeats, preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)

    return "\n".join(deduped)


def _cap_words(text: str, max_words: int = 3000) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _target_paths() -> List[str]:
    # Match the exercise brief: homepage + attempt /about and /pricing.
    return ["", "/about", "/pricing"]


def scrape_site(base_url: str) -> ScrapeResult:
    attempted: List[Tuple[str, str]] = []
    chunks: List[str] = []

    # 1) Homepage (required). If we cannot connect, treat the whole site as unreachable.
    homepage_url = urljoin(base_url.rstrip("/") + "/", "")
    html, status = _fetch_html(homepage_url)
    attempted.append((homepage_url, status))
    if status == "connect_failed":
        # If we can't connect to the homepage, /about and /pricing will not work either.
        raise ScrapeError(kind="unreachable", attempted=attempted)

    if html:
        text = _extract_visible_text(html)
        if text:
            chunks.append(f"URL: {homepage_url}\n{text}")
        else:
            attempted[-1] = (homepage_url, "no_text_extracted")

    # 2) Optional pages: /about, /pricing (best-effort)
    for path in ("/about", "/pricing"):
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        html2, status2 = _fetch_html(url)
        attempted.append((url, status2))
        if not html2:
            continue
        text2 = _extract_visible_text(html2)
        if not text2:
            attempted[-1] = (url, "no_text_extracted")
            continue
        chunks.append(f"URL: {url}\n{text2}")

    if not chunks:
        # We connected, but didn't get readable text (or were blocked).
        # We intentionally keep the error kinds coarse for user-friendly messaging.
        statuses = [s for (_, s) in attempted]
        if any(s == "no_text_extracted" for s in statuses):
            kind = "unscrapable"
        elif any(s in {"blocked", "http_error"} for s in statuses):
            kind = "blocked"
        else:
            kind = "unscrapable"
        raise ScrapeError(kind=kind, attempted=attempted)

    combined = _cap_words("\n\n".join(chunks), max_words=3000)
    return ScrapeResult(base_url=base_url, combined_text=combined, attempted=attempted)

