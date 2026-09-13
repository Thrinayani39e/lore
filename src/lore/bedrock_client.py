"""Thin wrapper around AWS Bedrock: Titan embeddings + Claude chat.

Mirrors the pattern used elsewhere in this workspace (verity/bedrock_client.py):
a cached boto3 client, a raw invoke_model call per model family, and no
external RAG/LLM framework in between.
"""
from __future__ import annotations

import json
from functools import lru_cache

import boto3

from lore.config import settings


@lru_cache(maxsize=1)
def _client():
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


def embed_text(text: str) -> list[float]:
    """Embed a single string via Titan Embeddings v2 (1024 dims)."""
    body = json.dumps({"inputText": text[:8000]})
    resp = _client().invoke_model(
        modelId=settings.bedrock_embed_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    embedding = payload.get("embedding")
    if not embedding:
        raise ValueError(f"Titan embedding response missing 'embedding': {payload}")
    return embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Titan v2 has no native batch endpoint on invoke_model; embed sequentially."""
    return [embed_text(t) for t in texts]


def generate_text(system: str, prompt: str, max_tokens: int = 1024) -> str:
    """Call Claude on Bedrock and return its text response.

    Uses the Bedrock Anthropic envelope (anthropic_version + messages), and
    is robust to a leading "thinking" content block by taking the last
    block of type "text".
    """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    resp = _client().invoke_model(
        modelId=settings.bedrock_chat_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    content = payload.get("content", [])
    text_blocks = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
    if not text_blocks:
        raise ValueError(f"Bedrock Claude response had no text block: {payload}")
    return text_blocks[-1].strip()


def generate_json(system: str, prompt: str, max_tokens: int = 1024) -> dict:
    """Like generate_text, but strips markdown code fences and parses JSON."""
    raw = generate_text(system, prompt, max_tokens=max_tokens)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse JSON from Bedrock response: {raw!r}") from e
