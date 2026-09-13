"""Local persistent vector store backed by Chroma.

Kept swappable behind a small interface so retrieval.py doesn't care
whether the backing store is Chroma, a SQL vector column, etc.
"""
from __future__ import annotations

from dataclasses import dataclass

import chromadb

from lore.config import settings

COLLECTION_NAME = "lore_history"


@dataclass
class StoredMatch:
    chunk_id: str
    text: str
    metadata: dict
    distance: float


class VectorStore:
    def __init__(self):
        self._client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self._collection = self._client.get_or_create_collection(
            COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, chunk_id: str, embedding: list[float], text: str, metadata: dict) -> None:
        self._collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def upsert_batch(
        self,
        chunk_ids: list[str],
        embeddings: list[list[float]],
        texts: list[str],
        metadatas: list[dict],
    ) -> None:
        if not chunk_ids:
            return
        self._collection.upsert(
            ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )

    def query(self, embedding: list[float], top_k: int = 6) -> list[StoredMatch]:
        result = self._collection.query(query_embeddings=[embedding], n_results=top_k)
        matches: list[StoredMatch] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]
        for i in range(len(ids)):
            matches.append(
                StoredMatch(chunk_id=ids[i], text=docs[i], metadata=metas[i] or {}, distance=dists[i])
            )
        return matches

    def count(self) -> int:
        return self._collection.count()

    def get_all(self, limit: int = 10000) -> list[StoredMatch]:
        """Full scan of everything indexed — used for corpus-level analysis
        (bus factor, digests) rather than a single semantic query."""
        result = self._collection.get(limit=limit, include=["documents", "metadatas"])
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        return [
            StoredMatch(chunk_id=ids[i], text=docs[i], metadata=metas[i] or {}, distance=0.0)
            for i in range(len(ids))
        ]
