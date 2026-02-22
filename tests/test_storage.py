from __future__ import annotations

from pathlib import Path

import pytest

from pith.storage import Storage


@pytest.mark.asyncio
async def test_storage_bootstrap_sessions_and_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    async with Storage(db_path) as storage:
        assert await storage.get_bootstrap_state() is False

        await storage.set_profile("agent", {"name": "pith", "nature": "assistant"})
        await storage.set_profile("user", {"name": "david"})
        assert await storage.get_bootstrap_state() is True

        session_id = await storage.ensure_active_session()
        await storage.add_message(session_id, "user", "hello")
        messages = await storage.get_recent_messages(session_id, limit=10)
        assert len(messages) == 1
        assert messages[0].content == "hello"

        memory_id = await storage.memory_save("remember this", kind="durable", tags=["pref"])
        assert memory_id > 0

        results = await storage.memory_search("remember", limit=5)
        assert results
        assert results[0].content == "remember this"
