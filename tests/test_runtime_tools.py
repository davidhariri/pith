from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from pith.config import Config, ModelConfig, RuntimeConfig, TelegramConfig
from pith.extensions import ExtensionRegistry
from pith.mcp_client import MCPClient
from pith.runtime import Runtime
from pith.storage import Storage


def _make_runtime(tmp_path: Path) -> tuple[Runtime, Storage]:
    workspace = tmp_path
    db_path = workspace / "memory.db"

    cfg = Config(
        version=1,
        runtime=RuntimeConfig(
            workspace_path=str(workspace),
            memory_db_path=str(db_path),
            log_dir=str(workspace / ".pith" / "logs"),
        ),
        model=ModelConfig(provider="test", model="test-model", api_key_env="TEST_KEY"),
        telegram=TelegramConfig(),
        mcp_servers={},
    )

    storage = Storage(db_path)
    extensions = ExtensionRegistry(workspace)
    mcp_client = MCPClient(workspace, {})
    runtime = Runtime(cfg, storage, extensions, mcp_client)
    return runtime, storage


@pytest.mark.asyncio
async def test_path_sandboxing(tmp_path: Path) -> None:
    runtime, storage = _make_runtime(tmp_path)

    # Valid workspace-relative path
    resolved = runtime._resolve_workspace_path("foo/bar.txt")
    assert resolved == (tmp_path / "foo" / "bar.txt").resolve()

    # Escape attempt
    with pytest.raises(ValueError, match="path escapes workspace"):
        runtime._resolve_workspace_path("../../etc/passwd")


@pytest.mark.asyncio
async def test_tool_registration_on_agent(tmp_path: Path) -> None:
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

        agent = runtime._build_agent(bootstrap=False, model=TestModel())

        # Check that individual tools are registered with proper names
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected = {
            "read",
            "write",
            "edit",
            "bash",
            "memory_save",
            "memory_search",
            "set_profile",
            "tool_call",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


@pytest.mark.asyncio
async def test_bootstrap_has_set_profile_tool(tmp_path: Path) -> None:
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

        agent = runtime._build_agent(bootstrap=True, model=TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "set_profile" in tool_names


@pytest.mark.asyncio
async def test_memory_tools_via_storage(tmp_path: Path) -> None:
    """Test memory save/search through storage directly (since tools are agent-registered)."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

        memory_id = await storage.memory_save("alpha memory", kind="durable", tags=["test"])
        assert memory_id > 0

        results = await storage.memory_search("alpha", limit=5)
        assert results
        assert results[0].content == "alpha memory"


@pytest.mark.asyncio
async def test_read_soul_file(tmp_path: Path) -> None:
    runtime, storage = _make_runtime(tmp_path)
    (tmp_path / "SOUL.md").write_text("I am pith.", encoding="utf-8")

    soul = runtime._read_soul()
    assert soul == "I am pith."


@pytest.mark.asyncio
async def test_read_soul_file_missing(tmp_path: Path) -> None:
    runtime, storage = _make_runtime(tmp_path)
    soul = runtime._read_soul()
    assert soul == ""
