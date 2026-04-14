import socket

from icp_bot.scrape import _hostname_is_safe, _is_blocked_ip, _validate_https_url


def test_is_blocked_ip_basic_ranges() -> None:
    assert _is_blocked_ip("127.0.0.1") is True  # loopback
    assert _is_blocked_ip("10.0.0.1") is True  # private
    assert _is_blocked_ip("192.168.1.10") is True  # private
    assert _is_blocked_ip("169.254.1.2") is True  # link-local
    assert _is_blocked_ip("169.254.169.254") is True  # cloud metadata
    assert _is_blocked_ip("8.8.8.8") is False  # public


def test_is_blocked_ip_invalid_string() -> None:
    assert _is_blocked_ip("not-an-ip") is True


def test_validate_https_url_accepts_basic_https() -> None:
    ok, status = _validate_https_url("https://example.com/")
    assert ok is True
    assert status == "ok"


def test_validate_https_url_rejects_http_and_credentials_and_ports() -> None:
    assert _validate_https_url("http://example.com")[0] is False
    assert _validate_https_url("https://user:pass@example.com")[0] is False
    assert _validate_https_url("https://example.com:444/")[0] is False


def test_hostname_is_safe_blocks_ip_literals() -> None:
    assert _hostname_is_safe("127.0.0.1") is False
    assert _hostname_is_safe("10.0.0.1") is False
    assert _hostname_is_safe("8.8.8.8") is True


def test_hostname_is_safe_uses_dns_and_blocks_if_any_ip_is_blocked(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        # Return one public and one private; should block.
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert _hostname_is_safe("example.com") is False


def test_hostname_is_safe_allows_when_all_resolved_ips_are_public(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert _hostname_is_safe("example.com") is True


def test_hostname_is_safe_returns_false_on_dns_error(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        raise OSError("dns failed")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert _hostname_is_safe("doesnotexist.invalid") is False

