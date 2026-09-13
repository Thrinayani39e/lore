from __future__ import annotations

from pydantic import BaseModel


class IngestRequest(BaseModel):
    repo: str  # any "owner/name"
    max_per_kind: int | None = 50


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict]


class FlagOut(BaseModel):
    id: int
    repo: str
    file_path: str
    message: str
    citations: list[dict]
    confidence: float
    created_at: str
