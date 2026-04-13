from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_parent_dir(db_path: str) -> None:
    p = Path(db_path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)


def connect(db_path: str) -> sqlite3.Connection:
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS icp_definition (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          industry TEXT NOT NULL,
          company_size_range TEXT NOT NULL,
          geography TEXT NOT NULL,
          keywords_json TEXT NOT NULL,
          exclusion_keywords_json TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS classifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          url TEXT NOT NULL,
          tier INTEGER NOT NULL,
          company_name TEXT,
          triggered_by TEXT NOT NULL,
          triggered_by_name TEXT,
          channel_id TEXT,
          thread_ts TEXT,
          created_at TEXT NOT NULL
        )
        """
    )
    # Lightweight migration for older DBs
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(classifications)").fetchall()}
    if "triggered_by_name" not in cols:
        cur.execute("ALTER TABLE classifications ADD COLUMN triggered_by_name TEXT")
    conn.commit()


def _json_list(raw: str) -> List[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def get_active_icp(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT industry, company_size_range, geography, keywords_json, exclusion_keywords_json, updated_at
        FROM icp_definition
        WHERE is_active = 1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    return {
        "industry": row["industry"],
        "company_size_range": row["company_size_range"],
        "geography": row["geography"],
        "keywords": _json_list(row["keywords_json"]),
        "exclusion_keywords": _json_list(row["exclusion_keywords_json"]),
        "updated_at": row["updated_at"],
    }


def upsert_active_icp(
    conn: sqlite3.Connection,
    *,
    industry: str,
    company_size_range: str,
    geography: str,
    keywords: List[str],
    exclusion_keywords: List[str],
) -> None:
    now = _utc_now_iso()
    conn.execute("UPDATE icp_definition SET is_active = 0 WHERE is_active = 1")
    conn.execute(
        """
        INSERT INTO icp_definition (
          industry, company_size_range, geography,
          keywords_json, exclusion_keywords_json,
          is_active, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (
            industry.strip(),
            company_size_range.strip(),
            geography.strip(),
            json.dumps([k.strip() for k in keywords if k.strip()]),
            json.dumps([k.strip() for k in exclusion_keywords if k.strip()]),
            now,
        ),
    )
    conn.commit()


def log_classification(
    conn: sqlite3.Connection,
    *,
    url: str,
    tier: int,
    company_name: Optional[str],
    triggered_by: str,
    triggered_by_name: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_ts: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO classifications (
          url, tier, company_name, triggered_by, triggered_by_name, channel_id, thread_ts, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            int(tier),
            (company_name or None),
            triggered_by,
            triggered_by_name,
            channel_id,
            thread_ts,
            _utc_now_iso(),
        ),
    )
    conn.commit()


def search_classifications(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    tier: Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    q = (q or "").strip()
    where = []
    params: List[Any] = []

    if q:
        where.append(
            "("
            "url LIKE ? OR "
            "triggered_by LIKE ? OR "
            "COALESCE(triggered_by_name, '') LIKE ? OR "
            "COALESCE(company_name, '') LIKE ?"
            ")"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if tier in (1, 2, 3):
        where.append("tier = ?")
        params.append(int(tier))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT id, url, tier, company_name, triggered_by, triggered_by_name, channel_id, thread_ts, created_at
        FROM classifications
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()

    return [dict(r) for r in rows]


def keyword_pools(conn: sqlite3.Connection, *, limit_rows: int = 200) -> Dict[str, List[str]]:
    """
    Returns distinct keyword pools from previously saved ICP definitions.
    Output keys: keywords, exclusion_keywords
    """
    rows = conn.execute(
        """
        SELECT keywords_json, exclusion_keywords_json
        FROM icp_definition
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (int(limit_rows),),
    ).fetchall()

    kw: List[str] = []
    ex: List[str] = []
    for r in rows:
        kw.extend(_json_list(r["keywords_json"]))
        ex.extend(_json_list(r["exclusion_keywords_json"]))

    def dedupe(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for it in items:
            s = str(it).strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    return {"keywords": dedupe(kw), "exclusion_keywords": dedupe(ex)}

