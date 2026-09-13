"""Corpus-level analysis on top of the indexed history — features that look
at the *whole* history at once, rather than answering one question or
checking one edit. This is where Lore stops being a Q&A bot and starts being
a product: knowledge-silo detection, auto-generated documentation, onboarding
briefs, and a standing risk digest.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lore.bedrock_client import generate_text
from lore.retrieval.retriever import search
from lore.retrieval.store import VectorStore

FILE_KINDS = {"commit", "pull_request"}


@dataclass
class FileOwnership:
    file_path: str
    authors: list[str]
    touches: int
    last_touched: str


def bus_factor_report(min_touches: int = 2, top_n: int = 10) -> list[FileOwnership]:
    """Finds files touched by exactly one author across the indexed history —
    knowledge silos where losing that one person means losing the file's
    context entirely. `min_touches` filters out one-off files that were only
    ever touched once (not a meaningful silo, just low activity).
    """
    store = VectorStore()
    matches = store.get_all()

    per_file: dict[str, dict] = defaultdict(lambda: {"authors": set(), "touches": 0, "last_touched": ""})

    seen_items = set()
    for m in matches:
        meta = m.metadata
        if meta.get("kind") not in FILE_KINDS:
            continue
        item_id = meta.get("item_id")
        # a multi-chunk item would otherwise be counted once per chunk
        dedup_key = (item_id, meta.get("file_paths", ""))
        if dedup_key in seen_items:
            continue
        seen_items.add(dedup_key)

        author = meta.get("author", "unknown")
        created_at = meta.get("created_at", "")
        for file_path in (p for p in meta.get("file_paths", "").split(",") if p):
            entry = per_file[file_path]
            entry["authors"].add(author)
            entry["touches"] += 1
            if created_at > entry["last_touched"]:
                entry["last_touched"] = created_at

    silos = [
        FileOwnership(file_path=fp, authors=sorted(d["authors"]), touches=d["touches"], last_touched=d["last_touched"])
        for fp, d in per_file.items()
        if len(d["authors"]) == 1 and d["touches"] >= min_touches
    ]
    silos.sort(key=lambda f: f.touches, reverse=True)
    return silos[:top_n]


ONBOARDING_SYSTEM = """You are Lore, writing an onboarding brief for a new contributor joining \
this codebase. You're given excerpts from the repo's real commit/PR/issue history. Synthesize a \
concise "start here" brief covering: (1) what this project actually does, (2) the key \
architectural decisions and why they were made, (3) known landmines / things that look like a \
good idea but were already tried and reverted, (4) who to ask about what (based on authorship \
patterns in the excerpts). Cite sources inline like [1], [2]. Be concrete and specific — pull \
real details from the excerpts, don't generalize."""

ONBOARDING_QUERIES = [
    "why is this project structured this way, key architecture decisions",
    "bug that was hard to fix or took a long time to resolve",
    "reverted change or approach that did not work",
    "getting started, setup, how to build and run",
]


def generate_onboarding_brief() -> str:
    all_matches = []
    seen_ids = set()
    for q in ONBOARDING_QUERIES:
        for m in search(q, top_k=5):
            if m.chunk_id not in seen_ids:
                seen_ids.add(m.chunk_id)
                all_matches.append(m)

    if not all_matches:
        return "No indexed history yet — run an ingest first."

    excerpt_text = "\n\n".join(
        f"[{i+1}] ({m.metadata.get('kind')}) {m.metadata.get('title')}\n{m.text}"
        for i, m in enumerate(all_matches)
    )
    citations = "\n".join(
        f"[{i+1}] {m.metadata.get('url')}" for i, m in enumerate(all_matches) if m.metadata.get("url")
    )
    brief = generate_text(ONBOARDING_SYSTEM, f"Excerpts:\n{excerpt_text}", max_tokens=1200)
    return f"{brief}\n\nSources:\n{citations}"


DOCUMENT_SYSTEM = """You are Lore, converting a repository's scattered PR/issue/commit history into \
permanent, structured documentation. Given excerpts of real history, write markdown content with \
sections: ## Key Decisions, ## Known Landmines, ## Architecture Rationale. Do NOT include a top-level \
title or heading — start directly with the first ## section, since the caller adds its own title. \
Under each bullet, cite the source like [1]. Be concrete and specific, using real details from the \
excerpts — this document replaces having to ask a teammate "why is this like this?". Do not invent \
anything not supported by the excerpts."""


def generate_institutional_memory_doc() -> tuple[str, list[dict]]:
    """Returns (markdown_content, citations) for a LORE.md doc synthesized
    from the whole indexed history."""
    all_matches = []
    seen_ids = set()
    for q in ONBOARDING_QUERIES + ["disagreement or long discussion about approach"]:
        for m in search(q, top_k=6):
            if m.chunk_id not in seen_ids:
                seen_ids.add(m.chunk_id)
                all_matches.append(m)

    excerpt_text = "\n\n".join(
        f"[{i+1}] ({m.metadata.get('kind')}) {m.metadata.get('title')}\n{m.text}"
        for i, m in enumerate(all_matches)
    )
    citations = [
        {"index": i + 1, "title": m.metadata.get("title", ""), "url": m.metadata.get("url", "")}
        for i, m in enumerate(all_matches)
    ]
    body = generate_text(DOCUMENT_SYSTEM, f"Excerpts:\n{excerpt_text}", max_tokens=1500)

    citation_md = "\n".join(f"[{c['index']}]: {c['url']}" for c in citations if c["url"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content = (
        f"# Institutional Memory\n\n_Auto-generated by Lore on {generated_at} from this repo's "
        f"real commit/PR/issue history. No human wrote this — verify before treating it as fact._\n\n"
        f"{body}\n\n---\n\n{citation_md}\n"
    )
    return content, citations


DIGEST_SYSTEM = """You are Lore, writing a short standing risk digest for a team lead. You're \
given (a) recent ambient flags Lore has raised, and (b) the most heavily-discussed items in the \
repo's history (proxy for contentious/unresolved topics). Write 3-5 bullet points on what's worth \
the team's attention right now — recurring debates, risk areas, anything trending toward being \
re-litigated. Be concise. Cite sources like [1] where relevant."""


def generate_risk_digest(recent_flags: list, top_n_discussed: int = 6) -> str:
    store = VectorStore()
    matches = store.get_all()

    seen_items = set()
    scored = []
    for m in matches:
        meta = m.metadata
        item_id = meta.get("item_id")
        if item_id in seen_items:
            continue
        seen_items.add(item_id)
        scored.append((len(m.text), m))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_discussed = [m for _, m in scored[:top_n_discussed]]

    flag_lines = "\n".join(f"- ({f.file_path}) {f.message}" for f in recent_flags) or "None recorded yet."
    discussed_lines = "\n".join(
        f"[{i+1}] ({m.metadata.get('kind')}) {m.metadata.get('title')} — {m.metadata.get('url')}"
        for i, m in enumerate(top_discussed)
    )

    prompt = f"Recent ambient flags:\n{flag_lines}\n\nMost heavily-discussed history items:\n{discussed_lines}"
    return generate_text(DIGEST_SYSTEM, prompt, max_tokens=600)
