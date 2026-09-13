"""Lore's FastAPI backend: ingest a repo, ask grounded questions, and stream
ambient flags to the dashboard as they're raised by the watcher.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from lore.api.schemas import ChatRequest, ChatResponse, IngestRequest
from lore.config import settings
from lore.ingestion.indexer import ingest_repo
from lore.integrations.teams_webhook import router as teams_router
from lore.retrieval.retriever import answer_question
from lore.storage.db import Database
from lore.watcher import flagger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lore.api")

app = FastAPI(title="Lore")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.include_router(teams_router)

_flag_queue: asyncio.Queue = asyncio.Queue()
_loop: asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def _register_flag_bridge():
    global _loop
    _loop = asyncio.get_event_loop()

    def on_flag(flag):
        if _loop:
            _loop.call_soon_threadsafe(_flag_queue.put_nowait, flag)

    flagger.subscribe(on_flag)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(ingest_repo, req.repo, settings.github_token, req.max_per_kind)
    return {"status": "started", "repo": req.repo}


@app.get("/ingest/status")
def ingest_status(repo: str):
    db = Database()
    status = db.get_repo_status(repo)
    return status or {"repo": repo, "indexed_chunks": 0, "last_ingested_at": None}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    answer = answer_question(req.question)
    return ChatResponse(answer=answer.text, citations=[asdict(c) for c in answer.citations])


@app.get("/flags")
def flags(repo: str | None = None, limit: int = 50):
    db = Database()
    return [asdict(f) for f in db.recent_flags(repo=repo, limit=limit)]


@app.get("/flags/stream")
async def flags_stream():
    async def event_generator():
        while True:
            flag = await _flag_queue.get()
            yield f"data: {json.dumps(asdict(flag))}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")
