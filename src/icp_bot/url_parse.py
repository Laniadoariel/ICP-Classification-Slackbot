from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


_URL_RE = re.compile(r"(https?://[^\s<>]+)", re.IGNORECASE)


def extract_first_url(text: str) -> str | None:
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    return m.group(1).rstrip(").,]")


def normalize_base_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL must include http(s):// and a host.")

    clean = parsed._replace(
        path="",
        params="",
        query="",
        fragment="",
    )
    return urlunparse(clean).rstrip("/")

