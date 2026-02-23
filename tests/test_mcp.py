from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pith.mcp import MCPRegistry, _parse_server_config

_FAKE_REQUEST = httpx.Request("POST", "https://fake.test/rpc")


def _make_response(status: int, json_data: dict) -> httpx.Response:
    return httpx.Response(status, json=json_data, request=_FAKE_REQUEST)


def _write_config(mcp_dir: Path, name: str, content: str) -> Path:
    mcp_dir.mkdir(parents=True, exist_ok=True)
    path = mcp_dir / f"{name}.yaml"
    path.write_text(content, encoding="utf-8")
    return path


# -- Config parsing --


def test_parse_server_config_basic(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text("url: https://mcp.example.com/rpc\n", encoding="utf-8")
    server = _parse_server_config("test", path)
    assert server.name == "test"
    assert server.url == "https://mcp.example.com/rpc"
    assert server.headers == {}


def test_parse_server_config_with_headers(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "url: https://mcp.example.com/rpc\nheaders:\n  Authorization: Bearer tok123\n",
        encoding="utf-8",
    )
    server = _parse_server_config("test", path)
    assert server.headers == {"Authorization": "Bearer tok123"}


def test_parse_server_config_env_var_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret_val")
    path = tmp_path / "test.yaml"
    path.write_text(
        "url: https://mcp.example.com/rpc\nheaders:\n  Authorization: Bearer ${MCP_TOKEN}\n",
        encoding="utf-8",
    )
    server = _parse_server_config("test", path)
    assert server.headers == {"Authorization": "Bearer secret_val"}


def test_parse_server_config_missing_url(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text("headers:\n  X-Key: val\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'url'"):
        _parse_server_config("test", path)


# -- Tool discovery --


def _tools_list_response(tools: list[dict]) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}


def _tool_call_response(text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": text}]},
    }


@pytest.mark.asyncio
async def test_discover_tools(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    _write_config(mcp_dir, "slack", "url: https://slack.mcp.test/rpc\n")

    mock_response = _make_response(
        200,
        _tools_list_response([
            {"name": "send_message", "description": "Send a Slack message", "inputSchema": {}},
            {"name": "list_channels", "description": "List channels", "inputSchema": {}},
        ]),
    )

    registry = MCPRegistry()
    with patch("pith.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await registry.refresh(mcp_dir)

    assert "mcp_slack_send_message" in registry.tools
    assert "mcp_slack_list_channels" in registry.tools
    assert registry.tools["mcp_slack_send_message"].description == "Send a Slack message"
    assert registry.list_tools() == ["mcp_slack_list_channels", "mcp_slack_send_message"]


@pytest.mark.asyncio
async def test_call_tool(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    _write_config(mcp_dir, "slack", "url: https://slack.mcp.test/rpc\n")

    discovery_response = _make_response(
        200,
        _tools_list_response([
            {"name": "send_message", "description": "Send", "inputSchema": {}},
        ]),
    )
    call_response = _make_response(200, _tool_call_response("message sent"))

    registry = MCPRegistry()
    with patch("pith.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[discovery_response, call_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await registry.refresh(mcp_dir)
        result = await registry.call(
            "mcp_slack_send_message", {"channel": "#general", "text": "hi"}
        )

    assert result == "message sent"


@pytest.mark.asyncio
async def test_call_unknown_tool() -> None:
    registry = MCPRegistry()
    result = await registry.call("mcp_nonexistent_tool")
    assert "unknown mcp tool" in result


@pytest.mark.asyncio
async def test_unreachable_server_skipped(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    _write_config(mcp_dir, "broken", "url: https://broken.mcp.test/rpc\n")
    _write_config(mcp_dir, "working", "url: https://working.mcp.test/rpc\n")

    working_response = _make_response(
        200,
        _tools_list_response([
            {"name": "ping", "description": "Ping", "inputSchema": {}},
        ]),
    )

    registry = MCPRegistry()
    with patch("pith.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()

        async def _route_post(url: str, **kwargs) -> httpx.Response:
            # Use the url from the payload context — we detect by checking
            # which server is being called based on call order
            call_count = mock_client.post.call_count
            if call_count == 1:
                # First call is to "broken" (alphabetically first)
                raise httpx.ConnectError("connection refused")
            return working_response

        mock_client.post = AsyncMock(side_effect=_route_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await registry.refresh(mcp_dir)

    # broken server skipped, working server discovered
    assert "mcp_broken_ping" not in registry.tools
    assert "mcp_working_ping" in registry.tools


@pytest.mark.asyncio
async def test_empty_mcp_dir(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    registry = MCPRegistry()
    await registry.refresh(mcp_dir)
    assert registry.tools == {}


@pytest.mark.asyncio
async def test_nonexistent_mcp_dir(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"  # doesn't exist
    registry = MCPRegistry()
    await registry.refresh(mcp_dir)
    assert registry.tools == {}


@pytest.mark.asyncio
async def test_get_tool_descriptions(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    _write_config(mcp_dir, "svc", "url: https://svc.test/rpc\n")

    mock_response = _make_response(
        200,
        _tools_list_response([
            {"name": "do_thing", "description": "Does a thing", "inputSchema": {}},
        ]),
    )

    registry = MCPRegistry()
    with patch("pith.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await registry.refresh(mcp_dir)

    descs = registry.get_tool_descriptions()
    assert descs == {"mcp_svc_do_thing": "Does a thing"}
