from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pith.config import MCPServerConfig
from pith.mcp_client import MCPClient


class _DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_mcp_discover_skips_unavailable_server(monkeypatch, tmp_path: Path) -> None:
    async def _post(*args, **kwargs):
        raise httpx.ConnectError("failed")

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    client = MCPClient(
        workspace_root=tmp_path,
        servers={
            "broken": MCPServerConfig(transport="http", url="http://example.invalid/mcp"),
        },
    )

    await client.discover()

    assert client.list_tools() == []
    assert len(client.discovery_warnings) == 1


@pytest.mark.asyncio
async def test_mcp_discover_and_call(monkeypatch, tmp_path: Path) -> None:
    async def _post(self, url, json=None, headers=None):
        if json and json.get("method") == "tools/list":
            return _DummyResponse({"result": {"tools": [{"name": "echo"}]}})
        if json and json.get("method") == "tools/call":
            return _DummyResponse({"result": {"content": [{"text": "ok"}]}})
        return _DummyResponse({})

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    client = MCPClient(
        workspace_root=tmp_path,
        servers={
            "good": MCPServerConfig(transport="http", url="http://example.test/mcp"),
        },
    )

    await client.discover()
    assert client.list_tools() == ["MCP__good__echo"]

    result = await client.call("MCP__good__echo", {"text": "hi"})
    assert result == "ok"
