from icp_bot.classify import (
    _company_size_match,
    _compute_tier,
    _detect_tech_stack_signal,
    _infer_geography,
    _normalize_company_size_label,
    _parse_range,
)


def test_parse_range_plus() -> None:
    # Testing upper limit for employees numbers
    assert _parse_range("1000+") == (1001, 10**9)
    assert _parse_range("1,000+ employees") == (1001, 10**9)


def test_parse_range_under() -> None:
    # Testing lower limit for employees numbers
    assert _parse_range("under 500") == (0, 500)
    assert _parse_range("less than 25") == (0, 25)


def test_parse_range_dash_and_words() -> None:
    # Testing range for employees numbers
    assert _parse_range("100-1000") == (100, 1000)
    assert _parse_range("100–1,000 employees") == (100, 1000)
    assert _parse_range("200 to 500") == (200, 500)


def test_company_size_match_overlap() -> None:
    # Testing overlap for company size
    assert _company_size_match("100-1000", "200-500") is True
    assert _company_size_match("100-1000", "1000+") is False
    assert _company_size_match("0-99", "1000+") is False


def test_company_size_match_categories() -> None:
    # Testing overlap for company size categories
    assert _company_size_match("100-1000", "Mid-market") is True
    assert _company_size_match("100-1000", "SMB") is True  
    assert _company_size_match("0-50", "Enterprise") is False


def test_normalize_company_size_label() -> None:
    # Testing normalization for company size labels
    # Small option
    assert _normalize_company_size_label("50") == "Small"
    # Mid-market options
    assert _normalize_company_size_label("100-999") == "Mid-market"
    assert _normalize_company_size_label("mid market") == "Mid-market"
    # Large option
    assert _normalize_company_size_label("1000+") == "Large"
    # Unknown options
    assert _normalize_company_size_label("") == "Unknown"
    assert _normalize_company_size_label("n/a") == "Unknown"


def test_compute_tier() -> None:
    # Testing tier computation for different criteria matches
    # Strong fit
    assert _compute_tier({"industry": True, "company_size": True, "geography": True}) == 1
    # Partial fit
    assert _compute_tier({"industry": True, "company_size": True, "geography": False}) == 2
    assert _compute_tier({"industry": True, "company_size": False, "geography": True}) == 2
    # Not a fit
    assert _compute_tier({"industry": True, "company_size": False, "geography": False}) == 3
    assert _compute_tier({"industry": False, "company_size": True, "geography": True}) == 3
    assert _compute_tier({"industry": False, "company_size": False, "geography": False}) == 3


def test_infer_geography_from_country_text() -> None:
    # Testing inference from country text
    assert _infer_geography(scraped_text="We are based in Germany.", source_url=None) == "Western Europe"
    assert _infer_geography(scraped_text="Our HQ is in Toronto, Canada.", source_url=None) == "North America"
    assert _infer_geography(scraped_text="Customers across Brazil and LATAM.", source_url=None) == "LATAM"


def test_infer_geography_from_cctld() -> None:
    # Testing inference from URL cctld
    assert _infer_geography(scraped_text="", source_url="https://example.de") == "Western Europe"
    assert _infer_geography(scraped_text="", source_url="https://example.com.br") == "LATAM"
    assert _infer_geography(scraped_text="", source_url="https://example.ca") == "North America"


def test_detect_tech_stack_signal() -> None:
    assert _detect_tech_stack_signal("We use HubSpot CRM.") == "HubSpot"
    assert _detect_tech_stack_signal("Powered by Salesforce Service Cloud") == "Salesforce"
    assert _detect_tech_stack_signal("No obvious tools mentioned") == "Not detected"

