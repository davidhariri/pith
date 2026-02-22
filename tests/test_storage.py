from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from pith.storage import Storage


@pytest.mark.asyncio
async def test_storage_bootstrap_sessions_and_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    async with Storage(db_path) as storage:
        assert await storage.get_bootstrap_state() is False

        await storage.set_profile("agent", "name", "pith")
        await storage.set_profile("agent", "nature", "assistant")
        await storage.set_profile("user", "name", "david")
        assert await storage.get_bootstrap_state() is True

        session_id = await storage.ensure_active_session()

        # Test ModelMessage round-tripping
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi there")]),
        ]
        await storage.append_messages(session_id, messages)

        history = await storage.get_message_history(session_id, limit=10)
        assert len(history) == 2
        assert history[0].kind == "request"
        assert history[1].kind == "response"

        # Memory round-trip
        memory_id = await storage.memory_save("remember this", kind="durable", tags=["pref"])
        assert memory_id > 0

        results = await storage.memory_search("remember", limit=5)
        assert results
        assert results[0].content == "remember this"


@pytest.mark.asyncio
async def test_storage_log_event_jsonl(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    log_path = tmp_path / "events.jsonl"

    async with Storage(db_path, log_path=log_path) as storage:
        await storage.log_event("test.event", payload={"key": "value"})

    assert log_path.exists()
    import json

    line = log_path.read_text().strip()
    entry = json.loads(line)
    assert entry["event"] == "test.event"
    assert entry["payload"]["key"] == "value"


@pytest.mark.asyncio
async def test_storage_compact_session(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    async with Storage(db_path) as storage:
        session_id = await storage.ensure_active_session()

        # Add enough messages to trigger compaction
        for i in range(10):
            msg = ModelRequest(parts=[UserPromptPart(content=f"message {i}")])
            await storage.append_messages(session_id, [msg])

        await storage.compact_session(session_id, keep_recent=3)

        remaining = await storage.get_message_history(session_id, limit=100)
        assert len(remaining) == 3

        summaries = await storage.list_session_summaries(session_id)
        assert len(summaries) == 1
