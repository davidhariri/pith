"""MCP (Model Context Protocol) HTTP client registry.

Discovers and calls tools from remote MCP servers configured via
workspace/mcp/<name>.yaml files. HTTP (streamable) transport only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from .config import _resolve_env_vars

logger = logging.getLogger(__name__)

_JSONRPC_VERSION = "2.0"


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPServer:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


class MCPRegistry:
    def __init__(self) -> None:
        self.servers: dict[str, MCPServer] = {}
        self.tools: dict[str, MCPTool] = {}

    async def refresh(self, mcp_dir: Path) -> None:
        """Read workspace/mcp/*.yaml, discover tools from each server."""
        self.servers.clear()
        self.tools.clear()

        if not mcp_dir.is_dir():
            return

        for path in sorted(mcp_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            name = path.stem
            try:
                server = _parse_server_config(name, path)
                self.servers[name] = server
                tools = await _discover_tools(server)
                for tool in tools:
                    full_name = f"mcp_{name}_{tool.name}"
                    self.tools[full_name] = MCPTool(
                        server=name,
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                    )
            except Exception as exc:
                logger.warning("mcp server '%s' skipped: %s", name, exc)

    async def call(self, full_name: str, args: dict[str, Any] | None = None) -> str:
        """Route mcp_<server>_<tool> to the right server's tools/call."""
        tool = self.tools.get(full_name)
        if tool is None:
            return f"unknown mcp tool: {full_name}"

        server = self.servers[tool.server]
        result = await _rpc_call(
            server,
            "tools/call",
            {"name": tool.name, "arguments": args or {}},
        )

        # MCP tools/call returns {content: [{type, text}, ...]}
        content = result.get("content", [])
        parts = [item.get("text", str(item)) for item in content]
        return "\n".join(parts)

    def list_tools(self) -> list[str]:
        return sorted(self.tools.keys())

    def get_tool_descriptions(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}


def _parse_server_config(name: str, path: Path) -> MCPServer:
    with path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}

    raw = _resolve_env_vars(raw)

    url = raw.get("url")
    if not url:
        raise ValueError(f"mcp config {path} missing 'url'")

    headers = raw.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError(f"mcp config {path} 'headers' must be a mapping")

    return MCPServer(name=name, url=url, headers={str(k): str(v) for k, v in headers.items()})


@dataclass
class _DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]


async def _discover_tools(server: MCPServer) -> list[_DiscoveredTool]:
    result = await _rpc_call(server, "tools/list", {})
    tools_raw = result.get("tools", [])
    out: list[_DiscoveredTool] = []
    for t in tools_raw:
        out.append(
            _DiscoveredTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
        )
    return out


async def _rpc_call(server: MCPServer, method: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jsonrpc": _JSONRPC_VERSION,
        "id": 1,
        "method": method,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=30, headers=server.headers) as client:
        resp = await client.post(server.url, json=payload)
        resp.raise_for_status()
        body = resp.json()

    if "error" in body:
        err = body["error"]
        raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")

    return body.get("result", {})
