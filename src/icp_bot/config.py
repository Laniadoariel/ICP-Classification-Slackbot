from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    slack_app_token: str
    openai_api_key: str
    openai_model: str
    sqlite_path: str
    seed_icp_on_startup: bool
    icp_definition: Dict[str, Any]


def _read_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_settings() -> Settings:
    load_dotenv()

    slack_bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    slack_app_token = os.getenv("SLACK_APP_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"
    sqlite_path = os.getenv("SQLITE_PATH", "data/icp.db").strip() or "data/icp.db"
    seed_icp_on_startup = _env_bool("SEED_ICP_ON_STARTUP", default=False)

    icp_env = os.getenv("ICP_DEFINITION_JSON", "").strip()
    if icp_env:
        icp_definition = json.loads(icp_env)
    else:
        repo_root = Path(__file__).resolve().parents[2]
        icp_definition = _read_json_file(repo_root / "config" / "icp_definition.json")

    missing = []
    if not slack_bot_token:
        missing.append("SLACK_BOT_TOKEN")
    if not slack_app_token:
        missing.append("SLACK_APP_TOKEN")
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return Settings(
        slack_bot_token=slack_bot_token,
        slack_app_token=slack_app_token,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        sqlite_path=sqlite_path,
        seed_icp_on_startup=seed_icp_on_startup,
        icp_definition=icp_definition,
    )

