from __future__ import annotations

import os
import sys
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Form, Request  # type: ignore[attr-defined]
from fastapi.responses import HTMLResponse, RedirectResponse  # type: ignore[attr-defined]
from fastapi.staticfiles import StaticFiles  # type: ignore[attr-defined]
from fastapi.templating import Jinja2Templates  # type: ignore[attr-defined]

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))

from icp_bot.config import load_settings  # noqa: E402
from icp_bot.db import (  # noqa: E402
    connect,
    init_db,
    keyword_pools,
    search_classifications,
    upsert_active_icp,
)


def _split_keywords(raw: str) -> List[str]:
    # Accept comma-separated or newline-separated lists.
    if not raw:
        return []
    parts = []
    for line in raw.replace(",", "\n").splitlines():
        s = line.strip()
        if s:
            parts.append(s)
    # de-dupe preserve order
    seen = set()
    out = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _normalize_industry(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    # Preserve common acronyms while allowing lowercase input.
    tokens = s.split()
    out = []
    for t in tokens:
        low = t.lower()
        if low == "b2b":
            out.append("B2B")
        elif low == "b2c":
            out.append("B2C")
        elif low == "saas":
            out.append("SaaS")
        else:
            out.append(t.capitalize() if t.islower() else t)
    return " ".join(out)


def _normalize_company_size_range(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    # If user types "100:" or "100" (no dash), interpret as 0-100.
    s2 = s.replace(" ", "")
    if "-" not in s2:
        digits = "".join(ch for ch in s2 if ch.isdigit())
        if digits:
            return f"0-{int(digits)}"
    return s


GEO_OPTIONS = [
    "North America",
    "Western Europe",
    "Eastern Europe",
    "LATAM",
    "APAC",
    "Middle East & Africa",
    "Global",
    "Other",
]


app = FastAPI(title="ICP Management Portal")

here = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(here / "templates"))
static_dir = here / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
def _startup() -> None:
    settings = load_settings()
    db_path = os.getenv("SQLITE_PATH", "data/icp.db")
    conn = connect(db_path)
    init_db(conn)
    conn.close()


@app.get("/", response_class=HTMLResponse)
def icp_form(request: Request):
    db_path = os.getenv("SQLITE_PATH", "data/icp.db")
    conn = connect(db_path)
    init_db(conn)
    pools = keyword_pools(conn)
    conn.close()

    # Always render an empty form (even if an active ICP exists in DB).
    icp = {
        "industry": "",
        "company_size_range": "",
        "geography": "",
        "keywords": [],
        "exclusion_keywords": [],
        "updated_at": "",
    }

    return templates.TemplateResponse(
        "icp_form.html",
        {
            "request": request,
            "icp": icp,
            "geo_options": GEO_OPTIONS,
            "keyword_pool": pools["keywords"],
            "exclusion_pool": pools["exclusion_keywords"],
        },
    )


@app.post("/icp")
def save_icp(
    industry: str = Form(...),
    company_size_range: str = Form(...),
    geography: str = Form(...),
    keywords: str = Form(""),
    exclusion_keywords: str = Form(""),
):
    db_path = os.getenv("SQLITE_PATH", "data/icp.db")
    conn = connect(db_path)
    init_db(conn)

    kw = _split_keywords(keywords)
    ex = _split_keywords(exclusion_keywords)
    # Prevent overlap (case-insensitive). Exclusion keywords win.
    ex_lower = {x.lower() for x in ex}
    kw = [x for x in kw if x.lower() not in ex_lower]

    upsert_active_icp(
        conn,
        industry=_normalize_industry(industry),
        company_size_range=_normalize_company_size_range(company_size_range),
        geography=geography,
        keywords=kw,
        exclusion_keywords=ex,
    )
    conn.close()
    return RedirectResponse(url="/", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, q: str = "", tier: Optional[str] = None):
    tier_int: Optional[int] = None
    try:
        t = (tier or "").strip()
        if t in ("1", "2", "3"):
            tier_int = int(t)
    except Exception:
        tier_int = None

    db_path = os.getenv("SQLITE_PATH", "data/icp.db")
    conn = connect(db_path)
    init_db(conn)
    rows = search_classifications(conn, q=q, tier=tier_int)
    conn.close()

    def format_israel(ts: str) -> str:
        try:
            s = (ts or "").replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Display in Israel time (UTC+3) per requirement.
            dt = dt.astimezone(timezone.utc) + timedelta(hours=3)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ts

    for r in rows:
        r["created_at_display"] = format_israel(str(r.get("created_at", "")))
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "rows": rows,
            "q": q,
            "tier": tier_int or "",
        },
    )


@app.get("/history.json")
def history_json(q: str = "", tier: Optional[str] = None, limit: int = 200):
    tier_int: Optional[int] = None
    try:
        t = (tier or "").strip()
        if t in ("1", "2", "3"):
            tier_int = int(t)
    except Exception:
        tier_int = None

    db_path = os.getenv("SQLITE_PATH", "data/icp.db")
    conn = connect(db_path)
    init_db(conn)
    rows = search_classifications(conn, q=q, tier=tier_int, limit=limit)
    conn.close()

    def format_israel(ts: str) -> str:
        try:
            s = (ts or "").replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc) + timedelta(hours=3)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ts

    out = []
    for r in rows:
        created_at = str(r.get("created_at", ""))
        out.append(
            {
                "id": r.get("id"),
                "created_at_display": format_israel(created_at),
                "url": r.get("url"),
                "tier": r.get("tier"),
                "company_name": r.get("company_name"),
                "triggered_by": r.get("triggered_by"),
                "triggered_by_name": r.get("triggered_by_name"),
            }
        )
    return {"rows": out}
