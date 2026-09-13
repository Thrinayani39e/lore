"""Runs the full ingest pipeline for one repo: fetch -> chunk -> embed -> store.

Also writes item metadata (title, url, author, kind, file paths) into SQLite
so the API/dashboard can resolve a chunk_id back into something citable
without re-hitting the GitHub API.
"""
from __future__ import annotations

import logging

from lore.bedrock_client import embed_text
from lore.ingestion.chunker import chunk_item
from lore.ingestion.github_ingest import GitHubIngestor
from lore.retrieval.store import VectorStore
from lore.storage.db import Database

logger = logging.getLogger("lore.indexer")


def ingest_repo(repo: str, token: str | None, max_per_kind: int | None = None) -> int:
    """Ingest `repo` ("owner/name") end to end. Returns number of chunks indexed."""
    store = VectorStore()
    db = Database()
    ingestor = GitHubIngestor(repo=repo, token=token)

    indexed = 0
    try:
        for item in ingestor.iter_all(max_per_kind=max_per_kind):
            db.upsert_history_item(item)
            for chunk in chunk_item(item):
                embedding = embed_text(chunk.text)
                store.upsert(
                    chunk_id=chunk.chunk_id,
                    embedding=embedding,
                    text=chunk.text,
                    metadata={
                        "item_id": item.id,
                        "kind": item.kind,
                        "title": item.title,
                        "url": item.url,
                        "author": item.author,
                        "created_at": item.created_at.isoformat(),
                        "file_paths": ",".join(item.file_paths),
                    },
                )
                indexed += 1
            logger.info("indexed %s (%s chunks so far)", item.id, indexed)
    finally:
        ingestor.close()

    db.set_repo_status(repo, indexed_chunks=indexed)
    return indexed
