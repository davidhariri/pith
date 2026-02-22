"""Tests for the HTTP API server."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from pith.config import Config, ModelConfig, RuntimeConfig, ServerConfig, TelegramConfig
from pith.extensions import ExtensionRegistry
from pith.mcp_client import MCPClient
from pith.runtime import Runtime
from pith.server import create_app
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
        server=ServerConfig(),
        mcp_servers={},
    )

    storage = Storage(db_path)
    extensions = ExtensionRegistry(workspace)
    mcp_client = MCPClient(workspace, {})
    runtime = Runtime(cfg, storage, extensions, mcp_client)
    return runtime, storage


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()
        app = create_app(runtime)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_session_new(client: httpx.AsyncClient) -> None:
    resp = await client.post("/session/new", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert isinstance(data["session_id"], str)


@pytest.mark.asyncio
async def test_session_info(client: httpx.AsyncClient) -> None:
    # Create a session first
    new_resp = await client.post("/session/new", json={})
    session_id = new_resp.json()["session_id"]

    resp = await client.get("/session/info", params={"session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert "bootstrap_complete" in data


@pytest.mark.asyncio
async def test_session_compact(client: httpx.AsyncClient) -> None:
    new_resp = await client.post("/session/new", json={})
    session_id = new_resp.json()["session_id"]

    resp = await client.post("/session/compact", json={"session_id": session_id})
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
