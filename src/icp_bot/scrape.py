from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import List, Tuple, Optional
from urllib.parse import urljoin, urlsplit

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


def _is_blocked_ip(ip: str) -> bool:
    """
    Return True if an IP address is not safe to fetch (SSRF protection)
    Blocks: loopback, private, link-local, multicast, unspecified, reserved
    Also blocks cloud metadata IP explicitly
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True

    # Cloud metadata 
    if str(addr) == "169.254.169.254":
        return True

    return bool(
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _validate_https_url(url: str) -> tuple[bool, str]:
    """
    Returns (ok, status_key).
    - ok - True means the URL is syntactically valid and allowed.
    - status_key is stable for user reporting.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return False, "invalid_url"

    if (parts.scheme or "").lower() != "https":
        return False, "invalid_url"
    if not parts.netloc:
        return False, "invalid_url"
    if parts.username or parts.password:
        return False, "invalid_url"
    if not parts.hostname:
        return False, "invalid_url"
    if parts.port not in (None, 443):
        return False, "invalid_url"

    return True, "ok"


def _hostname_is_safe(hostname: str) -> bool:
    # If hostname is already an IP, validate directly.
    try:
        ipaddress.ip_address(hostname)
        return not _is_blocked_ip(hostname)
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False

    for (_, _, _, _, sockaddr) in infos:
        # sockaddr: (ip, port) for v4; (ip, port, flow, scope) for v6
        ip = sockaddr[0]
        if _is_blocked_ip(ip):
            return False
    return True


def _fetch_html(url: str, timeout_s: float = 15) -> tuple[Optional[str], str]:
    """
    Returns (html, status_key).
    status_key is a stable, non-technical string for user-friendly reporting.
    """
    ok, status = _validate_https_url(url)
    if not ok:
        return None, status
    host = urlsplit(url).hostname or ""
    if not _hostname_is_safe(host):
        return None, "blocked_target"

    # Follow redirects manually so we can re-validate the target each hop.
    current = url
    for _ in range(6):  # max 5 redirects; loop runs 0..5
        try:
            resp = requests.get(
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=timeout_s,
                allow_redirects=False,
            )
        except requests.RequestException:
            return None, "connect_failed"

        # Redirect
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location") or ""
            if not loc:
                return None, "http_error"
            next_url = urljoin(current, loc)
            ok2, status2 = _validate_https_url(next_url)
            if not ok2:
                return None, status2
            host2 = urlsplit(next_url).hostname or ""
            if not _hostname_is_safe(host2):
                return None, "blocked_target"
            current = next_url
            continue

        code = resp.status_code
        if code == 404:
            return None, "not_found"
        if code in (401, 403):
            return None, "blocked"
        if code >= 400:
            return None, "http_error"

        return resp.text, "ok"

    return None, "http_error"


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
    if status in {"invalid_url", "blocked_target"}:
        # URL rejected by our security checks (HTTPS-only / SSRF protections).
        raise ScrapeError(kind="security_blocked", attempted=attempted)

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
        elif any(s in {"blocked_target", "invalid_url"} for s in statuses):
            kind = "security_blocked"
        elif any(s in {"blocked", "http_error"} for s in statuses):
            kind = "blocked"
        else:
            kind = "unscrapable"
        raise ScrapeError(kind=kind, attempted=attempted)

    combined = _cap_words("\n\n".join(chunks), max_words=3000)
    return ScrapeResult(base_url=base_url, combined_text=combined, attempted=attempted)

