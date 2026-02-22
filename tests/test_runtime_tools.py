from __future__ import annotations

import json
from pathlib import Path

import pytest

from pith.config import Config, ModelConfig, RuntimeConfig, TelegramConfig
from pith.extensions import ExtensionRegistry
from pith.mcp_client import MCPClient
from pith.runtime import Runtime
from pith.storage import Storage


@pytest.mark.asyncio
async def test_runtime_memory_tools(tmp_path: Path) -> None:
    workspace = tmp_path
    db_path = workspace / "memory.db"

    cfg = Config(
        version=1,
        runtime=RuntimeConfig(
            workspace_path=str(workspace),
            memory_db_path=str(db_path),
            log_dir=str(workspace / ".pith" / "logs"),
        ),
        model=ModelConfig(),
        telegram=TelegramConfig(),
        mcp_servers={},
    )

    storage = Storage(db_path)
    extensions = ExtensionRegistry(workspace)
    mcp_client = MCPClient(workspace, {})
    runtime = Runtime(cfg, storage, extensions, mcp_client)

    async with storage:
        await runtime.initialize()

        save_result = await runtime._tool_call("memory_save", {"content": "alpha memory"}, emit=None)
        assert save_result.startswith("memory_saved:")

        search_result = await runtime._tool_call("memory_search", {"query": "alpha"}, emit=None)
        payload = json.loads(search_result)
        assert payload
        assert payload[0]["content"] == "alpha memory"

        unknown = await runtime._tool_call("does_not_exist", {}, emit=None)
        assert unknown.startswith("RuntimeError:")
