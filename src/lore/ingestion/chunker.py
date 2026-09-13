"""Splits a HistoryItem's text into embedding-sized chunks.

Most PR/issue/commit bodies are short enough to embed whole; only long
discussions get split, on paragraph boundaries, to keep each chunk
coherent and cheap to embed.
"""
from __future__ import annotations

from dataclasses import dataclass

from lore.ingestion.github_ingest import HistoryItem

MAX_CHUNK_CHARS = 2000


@dataclass
class Chunk:
    chunk_id: str
    item: HistoryItem
    text: str


def chunk_item(item: HistoryItem) -> list[Chunk]:
    text = item.to_text()
    if len(text) <= MAX_CHUNK_CHARS:
        return [Chunk(chunk_id=f"{item.id}#0", item=item, text=text)]

    paragraphs = text.split("\n\n")
    chunks: list[Chunk] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > MAX_CHUNK_CHARS:
            chunks.append(Chunk(chunk_id=f"{item.id}#{len(chunks)}", item=item, text=buf))
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(Chunk(chunk_id=f"{item.id}#{len(chunks)}", item=item, text=buf))
    return chunks
