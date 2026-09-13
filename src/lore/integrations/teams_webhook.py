"""Microsoft Teams surface for Lore.

Outbound: flagger.py posts ambient flags to TEAMS_INCOMING_WEBHOOK_URL directly.

Inbound (asking Lore a question from Teams) requires registering a bot with
Azure Bot Framework, which needs an Azure AD app registration and a bot
channel — infra outside this repo's scope for a 2-day build. This module
exposes the same /chat logic as a plain HTTP endpoint that a Teams
"Outgoing Webhook" or Power Automate flow can call directly, which is the
fastest path to a working inbound demo without Azure bot registration.
"""
from __future__ import annotations

from fastapi import APIRouter

from lore.api.schemas import ChatRequest, ChatResponse
from lore.retrieval.retriever import answer_question

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/ask", response_model=ChatResponse)
def teams_ask(req: ChatRequest):
    """Point a Teams Outgoing Webhook or Power Automate HTTP action here."""
    from dataclasses import asdict

    answer = answer_question(req.question)
    return ChatResponse(answer=answer.text, citations=[asdict(c) for c in answer.citations])
