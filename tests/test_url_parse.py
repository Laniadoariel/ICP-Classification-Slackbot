import pytest

from icp_bot.url_parse import extract_first_url, normalize_base_url


def test_extract_first_url_none_cases() -> None:
    # Testing none URLs
    assert extract_first_url("") is None
    assert extract_first_url("no url here") is None


def test_extract_first_url_finds_http_or_https() -> None:
    # Testing extraction of HTTP or HTTPS URLs
    assert extract_first_url("check https://example.com") == "https://example.com"
    assert extract_first_url("check http://example.com") == "http://example.com"


def test_extract_first_url_strips_trailing_punctuation() -> None:
    # Testing stripping of trailing punctuation
    assert extract_first_url("see (https://example.com).") == "https://example.com"
    assert extract_first_url("see https://example.com, thanks") == "https://example.com"
    assert extract_first_url("see https://example.com]") == "https://example.com"


def test_normalize_base_url_rejects_missing_scheme_or_host() -> None:
    # Testing rejection of missing scheme or host
    with pytest.raises(ValueError):
        normalize_base_url("example.com")
    with pytest.raises(ValueError):
        normalize_base_url("https://")

