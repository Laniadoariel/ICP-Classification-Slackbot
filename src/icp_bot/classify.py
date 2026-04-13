from __future__ import annotations

import json
from dataclasses import dataclass
import re
from typing import Any, Dict, List

from openai import OpenAI
import tldextract


@dataclass(frozen=True)
class Classification:
    tier: int
    company_name: str
    industry: str
    company_size: str
    geography: str
    buying_signals: List[str]
    tech_stack_signal: str
    reasoning: List[str]
    criteria: Dict[str, bool]

GEO_OPTIONS = [
    "North America",
    "Western Europe",
    "Eastern Europe",
    "LATAM",
    "APAC",
    "Middle East & Africa",
    "Global",
    "Other",
    "Unknown",
]


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _soft_contains(a: str, b: str) -> bool:
    """
    Case-insensitive "soft" match.
    True if either string contains the other, ignoring extra whitespace.
    """
    na = _norm(a)
    nb = _norm(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def _parse_range(s: str) -> tuple[int | None, int | None]:
    """
    Extracts a numeric range from strings like:
    - "100-1000"
    - "100–1,000 employees"
    - "200 to 500"
    - "1000+"
    Returns (min, max). If only one number is present, returns (0, n).
    """
    raw = (s or "").replace(",", "")
    low_raw = raw.lower()
    nums = [int(x) for x in re.findall(r"\d+", raw)]
    if not nums:
        return (None, None)
    if len(nums) == 1:
        n = nums[0]
        # Common notation: "1000+" means at least 1000 employees.
        if "+" in raw or "plus" in low_raw:
            return (n, 10**9)
        # "under 500" / "less than 500"
        if "under" in low_raw or "less than" in low_raw or "below" in low_raw:
            return (0, n)
        # If we truly only have a single number, treat as an exact point.
        return (n, n)
    return (min(nums[0], nums[1]), max(nums[0], nums[1]))


def _company_size_match(icp_range: str, predicted_size: str) -> bool:
    icp_min, icp_max = _parse_range(icp_range)
    if icp_min is not None and icp_max is not None:
        p_min, p_max = _parse_range(predicted_size)
        if p_min is not None and p_max is not None:
            # overlap
            return not (p_max < icp_min or p_min > icp_max)

    # Fallback: map common categories to rough ranges
    p = _norm(predicted_size)
    if not p or p in {"unknown", "not sure", "n/a"}:
        return False
    cat_map: dict[str, tuple[int, int]] = {
        "startup": (0, 50),
        "small": (1, 100),
        "smb": (1, 200),
        "mid-market": (100, 1000),
        "mid market": (100, 1000),
        "enterprise": (1000, 1000000),
        "large": (1000, 1000000),
    }
    for k, (mn, mx) in cat_map.items():
        if k in p:
            icp_mn, icp_mx = _parse_range(icp_range)
            if icp_mn is None or icp_mx is None:
                return False
            return not (mx < icp_mn or mn > icp_mx)
    return False


def _normalize_company_size_label(raw: str) -> str:
    """
    Normalize company size output to one of:
    - Small
    - Mid-market
    - Large
    """
    s = (raw or "").strip()
    if not s:
        return "Unknown"

    low = _norm(s)
    if low in {"unknown", "not sure", "n/a"}:
        return "Unknown"

    # Already categorical?
    if "mid-market" in low or "mid market" in low:
        return "Mid-market"
    if "small" in low or "smb" in low or "startup" in low:
        return "Small"
    if "enterprise" in low or "large" in low:
        return "Large"

    # Numeric → category
    mn, mx = _parse_range(s)
    if mn is None or mx is None:
        return "Unknown"
    if mn >= 1000 or mx >= 1000:
        return "Large"
    if mn >= 100 or mx >= 100:
        return "Mid-market"
    return "Small"


def _compute_criteria(*, icp_definition: Dict[str, Any], industry: str, company_size: str, geography: str, tech_stack_signal: str) -> Dict[str, bool]:
    icp_industry = str((icp_definition or {}).get("industry") or "")
    icp_size = str((icp_definition or {}).get("company_size_range") or "")
    icp_geo = str((icp_definition or {}).get("geography") or "")

    industry_ok = _soft_contains(icp_industry, industry) if icp_industry else False
    geo_ok = _soft_contains(icp_geo, geography) if icp_geo else False
    size_ok = _company_size_match(icp_size, company_size) if icp_size else False

    tech = (tech_stack_signal or "").strip()
    tech_ok = bool(tech) and _norm(tech) not in {"not detected", "unknown", "n/a"}

    return {
        "industry": bool(industry_ok),
        "company_size": bool(size_ok),
        "geography": bool(geo_ok),
        "tech_stack_signal": bool(tech_ok),
    }


def _compute_tier(criteria: Dict[str, bool]) -> int:
    """
    Deterministic tiering based on criteria matches.
    Tier 1: strong fit (industry + size + geography)
    Tier 2: partial fit (industry + (size or geography))
    Tier 3: not a fit
    """
    industry = bool(criteria.get("industry"))
    size = bool(criteria.get("company_size"))
    geo = bool(criteria.get("geography"))

    if industry and size and geo:
        return 1
    if industry and (size or geo):
        return 2
    return 3


def _infer_geography(*, scraped_text: str, source_url: str | None = None) -> str:
    """
    Best-effort geography inference when the model returns "Unknown".
    This is intentionally simple and explainable; it only needs to be "good enough"
    to avoid returning Unknown when obvious signals exist (addresses, country names, ccTLDs).
    """
    t = _norm(scraped_text)

    def has_any(words: list[str]) -> bool:
        return any(_norm(w) in t for w in words)

    # ccTLD heuristics (very rough, but useful when present)
    if source_url:
        ext = tldextract.extract(source_url)
        suf = (ext.suffix or "").lower()  # e.g. "com.br", "de", "co.uk"
        latam_suffixes = {"com.br", "br", "com.mx", "mx", "com.ar", "ar", "cl", "com.co", "co", "pe", "uy"}
        na_suffixes = {"ca", "com.ca", "us"}
        we_suffixes = {"de", "fr", "nl", "be", "es", "it", "ie", "pt", "se", "no", "dk", "fi", "ch", "at", "co.uk", "uk"}
        ee_suffixes = {"pl", "cz", "sk", "hu", "ro", "bg", "lt", "lv", "ee", "si", "hr", "rs", "ua"}
        if suf in latam_suffixes:
            return "LATAM"
        if suf in na_suffixes:
            return "North America"
        if suf in we_suffixes:
            return "Western Europe"
        if suf in ee_suffixes:
            return "Eastern Europe"

    # Text heuristics: look for explicit region/country/company-contact patterns
    if has_any(["latin america", "latam", "mexico", "brazil", "argentina", "chile", "colombia", "peru"]):
        return "LATAM"
    if has_any(["united states", "usa", "u.s.", "canada", "mexico", "new york", "san francisco", "toronto", "vancouver"]):
        return "North America"
    if has_any(["europe", "eu", "united kingdom", "uk", "england", "germany", "france", "netherlands", "belgium", "spain", "italy", "sweden", "norway", "denmark", "finland", "switzerland", "austria", "ireland"]):
        return "Western Europe"
    if has_any(["poland", "czech", "slovakia", "hungary", "romania", "bulgaria", "lithuania", "latvia", "estonia", "serbia", "croatia", "ukraine"]):
        return "Eastern Europe"
    if has_any(["apac", "asia pacific", "singapore", "australia", "new zealand", "japan", "korea", "india"]):
        return "APAC"
    if has_any(["middle east", "africa", "uae", "dubai", "saudi", "qatar", "south africa"]):
        return "Middle East & Africa"
    if has_any(["global", "worldwide", "all regions", "international"]):
        return "Global"

    return "Unknown"


def _build_prompt(icp_definition: Dict[str, Any], scraped_text: str) -> tuple[str, str]:
    system = (
        "You are an ICP (Ideal Customer Profile) classifier. "
        "Return ONLY valid JSON. Do not wrap in markdown. Do not include extra keys."
    )

    user = (
        "Classify the company described by the website text against the ICP definition.\n\n"
        "ICP_DEFINITION_JSON:\n"
        f"{json.dumps(icp_definition, ensure_ascii=False)}\n\n"
        "SCRAPED_WEBSITE_TEXT:\n"
        f"{scraped_text}\n\n"
        "Return strict JSON with this exact shape:\n"
        "{\n"
        '  "tier": 1|2|3,\n'
        '  "company_name": "string",\n'
        '  "industry": "string (best guess, or \\"Unknown\\")",\n'
        '  "company_size": "one of [\\"Small\\", \\"Mid-market\\", \\"Large\\", \\"Unknown\\"]",\n'
        f'  "geography": "one of {GEO_OPTIONS} (best guess, or \\"Unknown\\")",\n'
        '  "buying_signals": ["short signal", "..."],\n'
        '  "tech_stack_signal": "string (e.g., \\"Salesforce\\", \\"HubSpot\\", \\"Not detected\\")",\n'
        '  "reasoning": ["bullet", "..."],\n'
        '  "criteria": {\n'
        '    "industry": true|false,\n'
        '    "company_size": true|false,\n'
        '    "geography": true|false,\n'
        '    "buying_signals": true|false,\n'
        '    "tech_stack_signal": true|false\n'
        "  }\n"
        "}\n"
        "Guidelines:\n"
        # We still request a tier for completeness, but we compute the final
        # Tier 1/2/3 deterministically from the criteria matches to avoid
        # inconsistent booleans/tier combos from the model.
        "- If unsure, prefer tier 3.\n"
        "- Keep reasoning to 3-6 short bullets.\n"
        "- buying_signals should be 0-5 items.\n"
        "- If you cannot find any tech stack clues, set tech_stack_signal to \"Not detected\" and criteria.tech_stack_signal=false.\n"
    )
    return system, user


def classify_company(
    *,
    openai_api_key: str,
    model: str,
    icp_definition: Dict[str, Any],
    scraped_text: str,
    source_url: str | None = None,
) -> Classification:
    client = OpenAI(api_key=openai_api_key)
    system, user = _build_prompt(icp_definition, scraped_text)

    # Use Chat Completions with JSON response formatting for reliable parsing.
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )

    content = resp.choices[0].message.content or ""
    data = json.loads(content)

    tier = int(data["tier"])
    if tier not in (1, 2, 3):
        raise ValueError("Model returned an invalid tier.")

    company_name = str(data.get("company_name") or "Unknown")
    industry = str(data.get("industry") or "Unknown")
    company_size = _normalize_company_size_label(str(data.get("company_size") or "Unknown"))
    geography = str(data.get("geography") or "Unknown")
    if _norm(geography) in {"unknown", "not sure", "n/a"}:
        geography = _infer_geography(scraped_text=scraped_text, source_url=source_url)
    buying_signals = list(data.get("buying_signals") or [])
    tech_stack_signal = str(data.get("tech_stack_signal") or "Not detected")
    reasoning = list(data.get("reasoning") or [])
    # We compute criteria deterministically from the saved ICP + extracted fields
    # (the model's internal boolean flags can be inconsistent).
    criteria = _compute_criteria(
        icp_definition=icp_definition,
        industry=industry,
        company_size=company_size,
        geography=geography,
        tech_stack_signal=tech_stack_signal,
    )
    # Final tier is derived from the criteria matches.
    tier = _compute_tier(criteria)

    return Classification(
        tier=tier,
        company_name=company_name,
        industry=industry,
        company_size=company_size,
        geography=geography,
        buying_signals=[str(x) for x in buying_signals][:8],
        tech_stack_signal=tech_stack_signal,
        reasoning=[str(x) for x in reasoning][:8],
        criteria=criteria,
    )

