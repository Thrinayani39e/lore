import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lore import bedrock_client


def _fake_bedrock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.__getitem__.side_effect = lambda k: {
        "body": MagicMock(read=lambda: json.dumps(payload).encode())
    }[k]
    return resp


@patch("lore.bedrock_client._client")
def test_embed_text_returns_vector(mock_client_fn):
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _fake_bedrock_response({"embedding": [0.1, 0.2, 0.3]})
    mock_client_fn.return_value = mock_client

    result = bedrock_client.embed_text("hello world")
    assert result == [0.1, 0.2, 0.3]


@patch("lore.bedrock_client._client")
def test_embed_text_raises_on_missing_embedding(mock_client_fn):
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _fake_bedrock_response({})
    mock_client_fn.return_value = mock_client

    with pytest.raises(ValueError):
        bedrock_client.embed_text("hello world")


@patch("lore.bedrock_client._client")
def test_generate_text_takes_last_text_block(mock_client_fn):
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _fake_bedrock_response(
        {
            "content": [
                {"type": "thinking", "text": "internal reasoning, should be ignored"},
                {"type": "text", "text": "final answer"},
            ]
        }
    )
    mock_client_fn.return_value = mock_client

    result = bedrock_client.generate_text("system prompt", "user prompt")
    assert result == "final answer"


@patch("lore.bedrock_client.generate_text")
def test_generate_json_strips_code_fences(mock_generate_text):
    mock_generate_text.return_value = '```json\n{"relevant": true, "confidence": 0.9}\n```'
    result = bedrock_client.generate_json("sys", "prompt")
    assert result == {"relevant": True, "confidence": 0.9}


@patch("lore.bedrock_client.generate_text")
def test_generate_json_raises_on_malformed_json(mock_generate_text):
    mock_generate_text.return_value = "not json at all"
    with pytest.raises(ValueError):
        bedrock_client.generate_json("sys", "prompt")
