"""Slack surface for Lore: a `/lore <question>` slash command that answers
grounded in indexed repo history, and an `/lore-ingest <owner/repo>` command
to kick off ingestion from Slack.

Run standalone with `python -m lore.integrations.slack_bot` (Socket Mode —
no public URL needed for local dev/demo).
"""
from __future__ import annotations

import logging
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from lore.config import settings
from lore.ingestion.indexer import ingest_repo
from lore.retrieval.retriever import answer_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lore.slack")

app = App(token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret)


@app.command("/lore")
def handle_lore_question(ack, respond, command):
    ack()
    question = command.get("text", "").strip()
    if not question:
        respond("Ask me something, e.g. `/lore why does the auth middleware retry twice?`")
        return

    respond(f":brain: Looking through the history for: _{question}_")
    answer = answer_question(question)
    citation_lines = "\n".join(
        f"[{c.index}] <{c.url}|{c.title}>" for c in answer.citations if c.url
    )
    text = answer.text if not citation_lines else f"{answer.text}\n\n{citation_lines}"
    respond(text)


@app.command("/lore-ingest")
def handle_ingest(ack, respond, command):
    ack()
    repo = command.get("text", "").strip()
    if not repo or "/" not in repo:
        respond("Usage: `/lore-ingest owner/repo`")
        return

    respond(f":hourglass_flowing_sand: Ingesting `{repo}` in the background — I'll post here when it's ready.")

    def run():
        count = ingest_repo(repo, settings.github_token)
        respond(f":white_check_mark: Indexed {count} chunks from `{repo}`. Ask away with `/lore`.")

    threading.Thread(target=run, daemon=True).start()


def main():
    if not (settings.slack_bot_token and settings.slack_app_token):
        raise SystemExit(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set to run the Slack bot (Socket Mode)."
        )
    handler = SocketModeHandler(app, settings.slack_app_token)
    handler.start()


if __name__ == "__main__":
    main()
