"""MCP tool integration layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .constants import DEFAULT_MCP_PREFIX
from .config import MCPServerConfig


@dataclass
class MCPTool:
    name: str
    server: str
    source: str


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, workspace_root: Path, servers: dict[str, MCPServerConfig]):
        self.workspace_root = workspace_root
        self.servers = servers
        self.known_tools: dict[str, MCPTool] = {}
        self.discovery_warnings: list[str] = []

    async def discover(self) -> None:
        self.known_tools = {}
        self.discovery_warnings = []
        for server_name, server_cfg in self.servers.items():
            try:
                tool_names = await self._discover_tools(server_name, server_cfg)
            except Exception as exc:
                warning = f"MCP server '{server_name}' unavailable during startup: {type(exc).__name__}: {exc}"
                self.discovery_warnings.append(warning)
                continue

            for tool_name in tool_names:
                fq = f"{DEFAULT_MCP_PREFIX}{server_name}__{tool_name}"
                self.known_tools[fq] = MCPTool(name=tool_name, server=server_name, source=server_name)

    async def _discover_tools(self, server_name: str, server_cfg: MCPServerConfig) -> list[str]:
        if server_cfg.tools:
            return [str(t) for t in server_cfg.tools]

        if server_cfg.transport == "http":
            if not server_cfg.url:
                return []
            payload = {
                "jsonrpc": "2.0",
                "id": f"pith-{server_name}-list",
                "method": "tools/list",
            }
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(server_cfg.url, json=payload, headers=server_cfg.headers or {})
                response.raise_for_status()
                data = response.json()
            result = data.get("result", {})
            return [t["name"] for t in result.get("tools", []) if isinstance(t, dict) and t.get("name")]

        return []

    def list_tools(self) -> list[str]:
        return sorted(self.known_tools.keys())

    async def call(self, full_name: str, args: dict[str, Any] | None = None) -> str:
        tool = self.known_tools.get(full_name)
        if tool is None:
            raise MCPError(f"Unknown MCP tool '{full_name}'")

        server_cfg = self.servers[tool.server]
        if server_cfg.transport == "http":
            if not server_cfg.url:
                raise MCPError(f"MCP server '{tool.server}' missing url")
            payload = {
                "jsonrpc": "2.0",
                "id": f"pith-{tool.server}-call",
                "method": "tools/call",
                "params": {
                    "name": tool.name,
                    "arguments": args or {},
                },
            }
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(server_cfg.url, json=payload, headers=server_cfg.headers or {})
                response.raise_for_status()
                data = response.json()
            return self._extract_mcp_result(data)

        raise MCPError(f"MCP transport '{server_cfg.transport}' is not implemented")

    def _extract_mcp_result(self, data: dict[str, Any]) -> str:
        if "error" in data:
            msg = data.get("error")
            raise MCPError(msg.get("message", str(msg)))
        result = data.get("result", {})
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(str(part["text"]))
                    else:
                        parts.append(str(part))
                return "\n".join(parts)
            if isinstance(content, str):
                return content
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result)
