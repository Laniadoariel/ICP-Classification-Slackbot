from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

import tldextract
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .classify import classify_company
from .config import load_settings
from .db import connect, get_active_icp, init_db, log_classification, upsert_active_icp
from .scrape import ScrapeError, scrape_site
from .slack_blocks import build_error_blocks, build_result_blocks
from .url_parse import extract_first_url, normalize_base_url


executor = ThreadPoolExecutor(max_workers=4)

def _fallback_company_name_from_url(base_url: str) -> str:
    ext = tldextract.extract(base_url)
    # ext.domain for https://foo.bar.com => "bar"
    name = (ext.domain or "").strip()
    if not name:
        return "Unknown"
    # Title-case common separators
    return name.replace("-", " ").replace("_", " ").title()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    settings = load_settings()
    logging.getLogger("icp_bot").info("Startup config: OPENAI_MODEL=%s", settings.openai_model)

    # Initialize DB. (Optionally) seed ICP once at startup.
    conn = connect(settings.sqlite_path)
    init_db(conn)
    if settings.seed_icp_on_startup and not get_active_icp(conn):
        # Seed from local config file to keep the app runnable.
        seed = settings.icp_definition or {}
        upsert_active_icp(
            conn,
            industry=str(seed.get("industry") or "B2B SaaS"),
            company_size_range=str(seed.get("company_size_range") or "100–1,000 employees"),
            geography=str(seed.get("geography") or "North America or Western Europe"),
            keywords=list(seed.get("keywords") or []),
            exclusion_keywords=list(seed.get("exclusion_keywords") or []),
        )
    conn.close()

    app = App(token=settings.slack_bot_token)

    @app.event("app_mention")
    def handle_mention(event, say, ack, logger):
        ack()  # must ack within 3 seconds

        text = event.get("text", "") or ""
        thread_ts = event.get("ts")

        url = extract_first_url(text)
        if not url:
            say(
                blocks=build_error_blocks(
                    "Please mention a URL after typing `@icp-bot`."
                ),
                thread_ts=thread_ts,
            )
            return

        def work():
            try:
                base_url = normalize_base_url(url)
                scraped = scrape_site(base_url).combined_text
                conn2 = connect(settings.sqlite_path)
                init_db(conn2)
                icp_from_db = get_active_icp(conn2) or settings.icp_definition
                result = classify_company(
                    openai_api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    icp_definition=icp_from_db,
                    scraped_text=scraped,
                )
                if not (result.company_name or "").strip() or (result.company_name or "").strip().lower() == "unknown":
                    result = result.__class__(  # type: ignore[misc]
                        **{**result.__dict__, "company_name": _fallback_company_name_from_url(base_url)}
                    )
                user_id = str(event.get("user") or "unknown")
                user_name = None
                try:
                    # Best-effort: requires the app to have the users:read scope.
                    info = app.client.users_info(user=user_id)
                    u = (info or {}).get("user") or {}
                    profile = (u.get("profile") or {}) if isinstance(u, dict) else {}
                    user_name = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or u.get("name")
                    )
                except Exception:
                    user_name = None
                log_classification(
                    conn2,
                    url=base_url,
                    tier=result.tier,
                    company_name=result.company_name,
                    triggered_by=user_id,
                    triggered_by_name=str(user_name) if user_name else None,
                    channel_id=str(event.get("channel") or "") or None,
                    thread_ts=str(event.get("ts") or "") or None,
                )
                conn2.close()
                say(blocks=build_result_blocks(result, base_url), thread_ts=thread_ts)
            except ScrapeError as e:
                if e.kind == "unreachable":
                    friendly = (
                        "*Site unreachable*\n"
                        f"Couldn't reach `{url}` — please check the URL and try again."
                    )
                    say(blocks=build_error_blocks(friendly), thread_ts=thread_ts)
                    return

                if e.kind == "unscrapable":
                    friendly = (
                        "*Website is unscrapable*\n"
                        + "The website opened, but there wasn’t readable text I could extract. Please try a different URL."
                    )
                else:
                    friendly = (
                        "*Website is not scrapable*\n"
                        + "The website appears to block automated access, or the content isn’t readable. Please try a different URL."
                    )
                say(blocks=build_error_blocks(friendly), thread_ts=thread_ts)
            except Exception as e:
                logger.error("Failure during classification: %s\n%s", e, traceback.format_exc())
                message = str(e) or "Unknown error"
                if "Error code: 429" in message or "insufficient_quota" in message:
                    say(
                        blocks=build_error_blocks(
                            "LLM reasoning failed. Please try again.",
                            title="LLM Failure",
                        ),
                        thread_ts=thread_ts,
                    )
                    return
                else:
                    friendly = f"*Error*: {message}\n\nTry again, or use a different URL."
                say(
                    blocks=build_error_blocks(
                        friendly
                    ),
                    thread_ts=thread_ts,
                )

        executor.submit(work)

    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()

