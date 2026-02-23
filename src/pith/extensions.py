"""Filesystem extension loader for tools and channels."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .mcp import MCPRegistry


@dataclass
class ExtensionTool:
    name: str
    module_path: Path
    fn: Callable[..., Any]
    description: str


@dataclass
class ExtensionChannel:
    name: str
    module_path: Path
    connect: Callable[..., Any]
    recv: Callable[..., Any]
    send: Callable[..., Any]


class ExtensionError(Exception):
    pass


class ExtensionRegistry:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.tools_dir = workspace_root / "extensions" / "tools"
        self.channels_dir = workspace_root / "extensions" / "channels"
        self.mcp_dir = workspace_root / "mcp"
        self.tools: dict[str, ExtensionTool] = {}
        self.channels: dict[str, ExtensionChannel] = {}
        self.mcp = MCPRegistry()

    async def refresh(self) -> tuple[dict[str, ExtensionTool], dict[str, ExtensionChannel]]:
        self.tools = await self._load_tools()
        self.channels = await self._load_channels()
        await self.mcp.refresh(self.mcp_dir)
        return self.tools, self.channels

    async def _load_tools(self) -> dict[str, ExtensionTool]:
        out: dict[str, ExtensionTool] = {}
        if not self.tools_dir.exists():
            return out

        for file in sorted(self.tools_dir.glob("*.py")):
            if file.name.startswith("_"):
                continue
            name = file.stem

            module = await self._load_module(file)
            if not hasattr(module, "run"):
                continue
            fn = module.run
            if not callable(fn):
                raise ExtensionError(f"tool {name} has non-callable run()")
            doc = inspect.getdoc(fn) or ""
            out[name] = ExtensionTool(name=name, module_path=file, fn=fn, description=doc)

        return out

    async def _load_channels(self) -> dict[str, ExtensionChannel]:
        out: dict[str, ExtensionChannel] = {}
        if not self.channels_dir.exists():
            return out

        for file in sorted(self.channels_dir.glob("*.py")):
            if file.name.startswith("_"):
                continue
            name = file.stem
            module = await self._load_module(file)
            for attr in ("connect", "recv", "send"):
                if not hasattr(module, attr):
                    raise ExtensionError(f"channel {name} missing {attr}()")
            out[name] = ExtensionChannel(
                name=name,
                module_path=file,
                connect=module.connect,
                recv=module.recv,
                send=module.send,
            )

        return out

    async def _load_module(self, path: Path) -> ModuleType:
        module_name = f"pith_extensions_{path.parent.name}_{path.stem}"
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ExtensionError(f"cannot import extension module {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        await asyncio.to_thread(spec.loader.exec_module, module)
        return module

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> str:
        if name not in self.tools:
            raise ExtensionError(f"Unknown extension tool '{name}'")

        tool = self.tools[name]
        parsed = args or {}
        try:
            result = tool.fn(**parsed)
            if asyncio.iscoroutine(result):
                result = await result
        except TypeError as exc:
            raise ExtensionError(f"tool '{name}' invocation error: {exc}") from exc

        return str(result)

    async def get_tool_descriptions(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}

    async def load_channel(self, channel_name: str) -> ExtensionChannel | None:
        if not self.channels:
            await self.refresh()
        return self.channels.get(channel_name)
