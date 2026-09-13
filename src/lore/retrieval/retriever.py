"""Semantic search over indexed history, plus two Claude-backed operations
built on top of it:

- answer_question: grounded Q&A with citations, for chat/Slack.
- judge_relevance: decides whether a code diff genuinely collides with
  retrieved history, and if so drafts the ambient flag message. This is
  what keeps the watcher from spamming false positives — retrieval alone
  is too noisy to surface unattended.
"""
from __future__ import annotations

from dataclasses import dataclass

from lore.bedrock_client import embed_text, generate_json, generate_text
from lore.retrieval.store import StoredMatch, VectorStore

ANSWER_SYSTEM = """You are Lore, a teammate who has read this repository's entire history of \
commits, pull requests, and issues. Answer the user's question using ONLY the provided \
excerpts. Cite sources inline like [1], [2] matching the numbered excerpts. If the excerpts \
don't contain the answer, say so plainly instead of guessing."""

RELEVANCE_SYSTEM = """You are Lore, an ambient teammate watching a developer's live edits. \
You are given the code they just changed and excerpts of past PRs/issues/commits that were \
semantically similar. Decide whether the past history contains something the developer should \
be warned about right now (e.g. this was tried before and reverted, this contradicts a past \
decision, this file has a known landmine). Respond with ONLY a JSON object:
{"relevant": true|false, "confidence": 0.0-1.0, "message": "one or two sentence heads-up citing [1] etc, or empty string if not relevant"}
Be conservative: most edits should NOT be flagged. Only flag genuine, specific collisions with \
history, not generic similarity."""


@dataclass
class Citation:
    index: int
    title: str
    url: str
    kind: str


@dataclass
class Answer:
    text: str
    citations: list[Citation]


def search(query: str, top_k: int = 6) -> list[StoredMatch]:
    store = VectorStore()
    embedding = embed_text(query)
    return store.query(embedding, top_k=top_k)


def _format_excerpts(matches: list[StoredMatch]) -> tuple[str, list[Citation]]:
    lines = []
    citations = []
    for i, m in enumerate(matches, start=1):
        meta = m.metadata
        lines.append(f"[{i}] ({meta.get('kind')}) {meta.get('title')}\n{m.text}")
        citations.append(Citation(index=i, title=meta.get("title", ""), url=meta.get("url", ""), kind=meta.get("kind", "")))
    return "\n\n".join(lines), citations


def answer_question(question: str, top_k: int = 6) -> Answer:
    matches = search(question, top_k=top_k)
    if not matches:
        return Answer(text="I don't have any indexed history for this repo yet — run an ingest first.", citations=[])

    excerpt_text, citations = _format_excerpts(matches)
    prompt = f"Question: {question}\n\nExcerpts:\n{excerpt_text}"
    text = generate_text(ANSWER_SYSTEM, prompt, max_tokens=800)
    return Answer(text=text, citations=citations)


def _format_review_comment(meta: dict, findings: list[dict]) -> str:
    lines = ["**Lore review** — checked this PR against the repo's own commit/PR/issue history.\n"]
    for f in findings:
        citation_md = ", ".join(
            f"[{c['title']}]({c['url']})" for c in f.get("citations", []) if c.get("url")
        )
        lines.append(f"**`{f['file']}`** (confidence {f['confidence']:.2f})\n{f['message']}\n\n{citation_md}\n")
    lines.append("_Posted automatically by [Lore](https://github.com/Thrinayani39e/lore) — no human reviewed this comment._")
    return "\n".join(lines)


def review_pull_request(
    repo: str, pr_number: int, token: str | None, max_files: int = 8, post_comment: bool = False
) -> dict:
    """Reviews an open (or any) PR against the repo's own indexed history —
    not a generic code review, but specifically: does this PR collide with a
    past decision, a reverted change, or a known landmine? Reuses the same
    judge_relevance the ambient watcher uses, just against real diff patches
    instead of live file content.

    `repo` is where the PR itself lives; the history it's checked against is
    whatever's already indexed (search() isn't repo-scoped), so this can be
    pointed at a demo/fork repo while still matching real project history.
    """
    from lore.ingestion.github_ingest import GitHubIngestor

    ingestor = GitHubIngestor(repo=repo, token=token)
    try:
        meta = ingestor.get_pull_request_meta(pr_number)
        files = ingestor.get_pull_request_files(pr_number)

        from dataclasses import asdict

        findings = []
        for f in files[:max_files]:
            patch = f.get("patch")
            if not patch:
                continue
            result = judge_relevance(f["filename"], patch)
            if result.get("relevant") and result.get("confidence", 0) >= 0.5:
                result["citations"] = [asdict(c) for c in result.get("citations", [])]
                findings.append({"file": f["filename"], **result})

        if post_comment and findings:
            ingestor.post_pull_request_comment(pr_number, _format_review_comment(meta, findings))
    finally:
        ingestor.close()

    return {"repo": repo, "pr_number": pr_number, "meta": meta, "findings": findings}


def judge_relevance(file_path: str, diff_or_content: str, top_k: int = 5) -> dict:
    """Returns {"relevant": bool, "confidence": float, "message": str, "citations": [Citation]}."""
    query = f"{file_path}\n{diff_or_content[:3000]}"
    matches = search(query, top_k=top_k)
    if not matches:
        return {"relevant": False, "confidence": 0.0, "message": "", "citations": []}

    excerpt_text, citations = _format_excerpts(matches)
    prompt = f"File: {file_path}\n\nCurrent change:\n{diff_or_content[:3000]}\n\nRelated history:\n{excerpt_text}"
    result = generate_json(RELEVANCE_SYSTEM, prompt, max_tokens=400)
    result["citations"] = citations
    return result
