"""Turns a relevance judgement into a persisted Flag and pushes it to
whatever live surfaces are configured (dashboard SSE queue, Slack, Teams).
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from lore.config import settings
from lore.retrieval.retriever import judge_relevance
from lore.storage.db import Database, Flag

logger = logging.getLogger("lore.flagger")

CONFIDENCE_THRESHOLD = 0.6

# Simple in-memory pub/sub so the FastAPI SSE endpoint can stream new flags
# without a message broker — fine for a single-process demo deployment.
_subscribers: list = []


def subscribe(callback) -> None:
    _subscribers.append(callback)


def _broadcast(flag: Flag) -> None:
    for cb in list(_subscribers):
        try:
            cb(flag)
        except Exception:
            logger.exception("subscriber callback failed")


def evaluate_and_flag(repo: str, file_path: str, content: str) -> Flag | None:
    result = judge_relevance(file_path, content)
    if not result.get("relevant") or result.get("confidence", 0) < CONFIDENCE_THRESHOLD:
        return None

    citations = [asdict(c) for c in result.get("citations", [])]
    db = Database()
    flag = db.add_flag(
        repo=repo,
        file_path=file_path,
        message=result["message"],
        citations=citations,
        confidence=result["confidence"],
    )
    logger.info("flag raised on %s: %s", file_path, flag.message)
    _broadcast(flag)

    _post_to_slack(flag)
    _post_to_teams(flag)
    return flag


def _post_to_slack(flag: Flag) -> None:
    if not settings.slack_bot_token:
        return
    try:
        from slack_sdk import WebClient

        client = WebClient(token=settings.slack_bot_token)
        citation_lines = "\n".join(f"- <{c['url']}|{c['title']}>" for c in flag.citations if c.get("url"))
        text = f":brain: *Lore flag* on `{flag.file_path}`\n{flag.message}\n{citation_lines}"
        client.chat_postMessage(channel=settings.slack_flags_channel, text=text)
    except Exception:
        logger.exception("failed to post flag to slack")


def _post_to_teams(flag: Flag) -> None:
    if not settings.teams_incoming_webhook_url:
        return
    try:
        import httpx

        citation_lines = "\n\n".join(f"[{c['title']}]({c['url']})" for c in flag.citations if c.get("url"))
        card = {
            "text": f"**Lore flag** on `{flag.file_path}`\n\n{flag.message}\n\n{citation_lines}"
        }
        httpx.post(settings.teams_incoming_webhook_url, json=card, timeout=10.0)
    except Exception:
        logger.exception("failed to post flag to teams")
