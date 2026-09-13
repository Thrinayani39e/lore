import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lore.ingestion.chunker import chunk_item
from lore.ingestion.github_ingest import HistoryItem


def make_item(body: str) -> HistoryItem:
    return HistoryItem(
        kind="pull_request",
        id="pr:test/repo#1",
        title="Add retry logic to the payment client",
        body=body,
        author="octocat",
        created_at=datetime.now(timezone.utc),
        url="https://github.com/test/repo/pull/1",
        file_paths=["src/payments/client.py"],
    )


def test_short_item_produces_single_chunk():
    item = make_item("Short discussion body.")
    chunks = chunk_item(item)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "pr:test/repo#1#0"
    assert "Add retry logic" in chunks[0].text
    assert "src/payments/client.py" in chunks[0].text


def test_long_item_splits_on_paragraphs():
    long_body = "\n\n".join(f"Paragraph {i} " + ("x" * 300) for i in range(20))
    item = make_item(long_body)
    chunks = chunk_item(item)
    assert len(chunks) > 1
    # every chunk id is unique and ordered
    ids = [c.chunk_id for c in chunks]
    assert ids == sorted(ids)
    # no chunk exceeds the soft limit by more than one paragraph's worth
    for c in chunks:
        assert len(c.text) < 2500


def test_chunk_ids_are_stable_per_item():
    item = make_item("Body")
    first = [c.chunk_id for c in chunk_item(item)]
    second = [c.chunk_id for c in chunk_item(item)]
    assert first == second
