from __future__ import annotations

from typing import Any, Dict, List

from .classify import Classification


def _clamp_text(s: str, *, max_len: int) -> str:
    s2 = (s or "").strip()
    if len(s2) <= max_len:
        return s2
    return s2[: max(0, max_len - 1)].rstrip() + "…"


def _tier_label(tier: int) -> str:
    return {
        1: "Tier 1",
        2: "Tier 2",
        3: "Tier 3",
    }.get(tier, f"Tier {tier}")


def _bool_emoji(value: bool) -> str:
    # Keep it plain text; Slack will render :white_check_mark: etc.
    return ":white_check_mark:" if value else ":x:"

def _tier_emoji(tier: int) -> str:
    # User-facing overall tier indicator: Tier 3 should show an X.
    if tier == 3:
        return ":x:"
    return ":white_check_mark:"


def build_result_blocks(result: Classification, url: str) -> List[Dict[str, Any]]:
    tier_line = f"*ICP Classification*: {_tier_label(result.tier)} {_tier_emoji(result.tier)}"

    # Keep sections short to avoid Slack collapsing blocks behind "See more".
    reasoning = [str(b).strip() for b in (result.reasoning or []) if str(b).strip()]
    reasoning = reasoning[:4]
    reasoning_lines = "\n".join([f"• {_clamp_text(b, max_len=140)}" for b in reasoning]) or "• (no reasoning provided)"

    criteria_lines = "\n".join(
        [
            f"{_bool_emoji(result.criteria.get('industry', False))} *Industry*: {_clamp_text(result.industry, max_len=80) or 'Unknown'}",
            f"{_bool_emoji(result.criteria.get('company_size', False))} *Company size*: {_clamp_text(result.company_size, max_len=80) or 'Unknown'}",
            f"{_bool_emoji(result.criteria.get('geography', False))} *Geography*: {_clamp_text(result.geography, max_len=80) or 'Unknown'}",
            f"{_bool_emoji(result.criteria.get('tech_stack_signal', False))} *Tech stack signal*: {_clamp_text(result.tech_stack_signal, max_len=80) or 'Not detected'}",
        ]
    )

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":office: *{result.company_name}* — {url}\n\n{tier_line}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reasoning*\n{reasoning_lines}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*ICP Criteria Match*\n{criteria_lines}"},
        },
    ]


def build_error_blocks(message: str, *, title: str = "ICP classification failed") -> List[Dict[str, Any]]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
    ]

