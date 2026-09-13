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

from lore.bedrock_client import generate_text
from lore.config import settings
from lore.ingestion.indexer import ingest_repo
from lore.ingestion.github_ingest import GitHubIngestor
from lore.retrieval.insights import (
    bus_factor_report,
    generate_institutional_memory_doc,
    generate_onboarding_brief,
    generate_risk_digest,
)
from lore.retrieval.retriever import answer_question, review_pull_request
from lore.storage.db import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lore.slack")

app = App(token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret)

CAPABILITIES = """Lore is an ambient teammate that ingests a GitHub repo's commits, pull requests, \
and issues into a searchable index, then does two kinds of things: it watches your local checkout \
and proactively flags when a live edit collides with something in the repo's own history (no one \
has to ask), and it exposes that history through these Slack commands:

- `/lore <question>` — ask anything about the repo; answers grounded in real history, with citations.
- `/lore-ingest owner/repo` — index any GitHub repo (public or private with a token).
- `/lore-review owner/repo#123 [--post]` — reviews a real PR's diff against the repo's own history \
(not style/lint — specifically checks for collisions with past decisions or reverted changes). \
`--post` leaves a real comment on the PR.
- `/lore-bus-factor` — finds files touched by exactly one author across history (knowledge silos — \
what breaks if that person leaves).
- `/lore-onboard` — generates a "start here" brief for a new contributor from the real history: \
architecture decisions, known landmines, who to ask about what.
- `/lore-digest [owner/repo]` — a standing risk report combining recent ambient flags with the most \
heavily-discussed history items, for team leads.
- `/lore-document owner/repo [--post]` — synthesizes a structured `LORE.md` (decisions, landmines, \
architecture rationale) from history; `--post` opens a real PR adding it to the repo.

Lore is not a one-shot "ask an AI to read the code" tool — it's a small always-on service with its \
own ingestion pipeline and vector index, so it accumulates and reuses history over time rather than \
re-reading everything from scratch on every question."""

HELP_SYSTEM = f"""You are Lore, answering a question about your own capabilities as a product — not \
about any ingested repo's code. Use ONLY the following accurate description of what you can do. Be \
concise and concrete; if asked about something you don't do, say so plainly rather than guessing.

{CAPABILITIES}"""


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


@app.command("/lore-review")
def handle_review(ack, respond, command):
    ack()
    text = command.get("text", "").strip()
    post_comment = "--post" in text
    text = text.replace("--post", "").strip()

    repo, _, pr_ref = text.partition("#")
    if not pr_ref:
        repo, _, pr_ref = text.rpartition(" ")
    repo = repo.strip()
    pr_ref = pr_ref.strip()
    if not repo or "/" not in repo or not pr_ref.isdigit():
        respond("Usage: `/lore-review owner/repo#123` (add `--post` to also post a comment on the PR)")
        return

    pr_number = int(pr_ref)
    respond(f":mag: Reviewing `{repo}#{pr_number}` against its own history...")

    def run():
        result = review_pull_request(repo, pr_number, settings.github_token, post_comment=post_comment)
        meta = result["meta"]
        findings = result["findings"]
        if not findings:
            respond(f":white_check_mark: No history collisions found in <{meta['url']}|{meta['title']}>.")
            return

        lines = [f":warning: *Lore review* of <{meta['url']}|{meta['title']}>"]
        for f in findings:
            citation_lines = ", ".join(f"<{c['url']}|{c['title']}>" for c in f.get("citations", []) if c.get("url"))
            lines.append(f"\n*`{f['file']}`* (confidence {f['confidence']:.2f})\n{f['message']}\n{citation_lines}")
        if post_comment:
            lines.append(f"\n:speech_balloon: Posted as a comment on <{meta['url']}|the PR>.")
        respond("\n".join(lines))

    threading.Thread(target=run, daemon=True).start()


@app.command("/lore-bus-factor")
def handle_bus_factor(ack, respond, command):
    ack()
    respond(":male-detective: Scanning authorship history for knowledge silos...")

    def run():
        silos = bus_factor_report()
        if not silos:
            respond(":white_check_mark: No single-owner hotspots found in the indexed history.")
            return
        lines = [":warning: *Bus factor report* — files only one person has ever touched:\n"]
        for s in silos:
            lines.append(f"• `{s.file_path}` — {s.touches} touches, only *{s.authors[0]}*, last touched {s.last_touched[:10]}")
        respond("\n".join(lines))

    threading.Thread(target=run, daemon=True).start()


@app.command("/lore-onboard")
def handle_onboard(ack, respond, command):
    ack()
    respond(":books: Reading through the whole history to write an onboarding brief...")

    def run():
        brief = generate_onboarding_brief()
        respond(f":wave: *Onboarding brief*\n\n{brief}")

    threading.Thread(target=run, daemon=True).start()


@app.command("/lore-digest")
def handle_digest(ack, respond, command):
    ack()
    repo = command.get("text", "").strip() or None
    respond(":newspaper: Building the risk digest...")

    def run():
        db = Database()
        flags = db.recent_flags(repo=repo, limit=20)
        digest = generate_risk_digest(flags)
        respond(f":newspaper: *Risk digest*\n\n{digest}")

    threading.Thread(target=run, daemon=True).start()


@app.command("/lore-document")
def handle_document(ack, respond, command):
    ack()
    text = command.get("text", "").strip()
    post = "--post" in text
    repo = text.replace("--post", "").strip()
    if not repo or "/" not in repo:
        respond("Usage: `/lore-document owner/repo` (add `--post` to open a real PR adding LORE.md)")
        return

    respond(f":memo: Synthesizing an institutional memory doc for `{repo}`...")

    def run():
        content, citations = generate_institutional_memory_doc()
        if not post:
            preview = content[:2500] + ("\n\n... (truncated preview)" if len(content) > 2500 else "")
            respond(f"{preview}\n\n_Add `--post` to open a real PR adding this as `LORE.md`._")
            return

        branch = "lore/institutional-memory"
        ingestor = GitHubIngestor(repo=repo, token=settings.github_token)
        try:
            try:
                ingestor.create_branch(branch)
            except Exception:
                pass  # branch may already exist from a prior run
            ingestor.create_or_update_file(
                "LORE.md", content, branch=branch, message="Add auto-generated institutional memory doc (Lore)"
            )
            pr = ingestor.create_pull_request(
                title="Add auto-generated institutional memory doc",
                body="Generated by Lore from this repo's real commit/PR/issue history. Adds `LORE.md`.",
                head_branch=branch,
            )
        finally:
            ingestor.close()

        respond(f":white_check_mark: Opened <{pr['html_url']}|{pr['title']}> adding `LORE.md`.")

    threading.Thread(target=run, daemon=True).start()


@app.command("/lore-help")
def handle_help(ack, respond, command):
    ack()
    question = command.get("text", "").strip()
    if not question:
        respond(f":brain: *What Lore can do*\n\n{CAPABILITIES}")
        return

    respond(":thinking_face: ...")
    answer = generate_text(HELP_SYSTEM, question, max_tokens=500)
    respond(answer)


def main():
    if not (settings.slack_bot_token and settings.slack_app_token):
        raise SystemExit(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set to run the Slack bot (Socket Mode)."
        )
    handler = SocketModeHandler(app, settings.slack_app_token)
    handler.start()


if __name__ == "__main__":
    main()
