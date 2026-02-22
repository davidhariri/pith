"""Core loop and tool dispatch."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext
from .constants import (
    DEFAULT_MCP_PREFIX,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    SOUL_FILE,
    DEFAULT_MEMORY_TOP_N,
)
from .config import Config
from .extensions import ExtensionRegistry
from .mcp_client import MCPClient
from .storage import Message, MemoryEntry, Storage


@dataclass
class ChatEvent:
    type: str
    content: str


class Runtime:
    def __init__(self, cfg: Config, storage: Storage, extensions: ExtensionRegistry, mcp_client: MCPClient) -> None:
        self.cfg = cfg
        self.storage = storage
        self.extensions = extensions
        self.mcp_client = mcp_client
        self.workspace = Path(cfg.runtime.workspace_path)
        self.log_dir = Path(cfg.runtime.log_dir)
        self.agent: Agent | None = None
        self.log_path = self.log_dir / "events.jsonl"
        self.storage.log_path = self.log_path

    async def initialize(self) -> None:
        await self.storage.ensure_schema()
        await self.extensions.refresh()
        await self.mcp_client.discover()
        for warning in self.mcp_client.discovery_warnings:
            print(f"[warn] {warning}")
            await self.storage.log_event("mcp.discovery.warning", level="warning", payload={"message": warning})
        await self._ensure_bootstrap_state()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_bootstrap_state(self) -> None:
        complete = await self.storage.get_bootstrap_state()
        await self.storage.set_bootstrap_complete(complete)
        if not complete:
            await self.storage.set_app_state("bootstrap_note", "identity not fully configured")

    def _build_agent(self, bootstrap: bool) -> Agent:
        system_prompt = self._system_prompt(bootstrap)
        model_name = f"{self.cfg.model.provider}:{self.cfg.model.model}"
        self.agent = Agent(
            model_name,
            system_prompt=system_prompt,
            output_type=str,
        )

        @self.agent.tool
        async def tool_call(ctx: RunContext["RuntimeContext"], name: str, args: dict[str, Any] | None = None) -> str:
            return await self._tool_call(name, args or {}, emit=ctx.deps.emit)

        return self.agent

    async def refresh_extensions(self) -> None:
        await self.extensions.refresh()

    async def list_tools(self) -> list[str]:
        tool_names = [
            "tool_call",
            "read",
            "write",
            "edit",
            "bash",
            "memory_save",
            "memory_search",
        ]
        await self.extensions.refresh()
        tool_names.extend(sorted(self.extensions.tools.keys()))
        tool_names.extend(self.mcp_client.list_tools())
        return tool_names

    async def _tool_call(self, name: str, args: dict[str, Any], emit: Any) -> str:
        await self.storage.log_event("tool_call.start", payload={"name": name, "args": args})

        if emit is not None:
            emit(ChatEvent("tool_call", f"→ {name}"))

        try:
            if name == "read":
                return await self._read_file(args)
            if name == "write":
                return await self._write_file(args)
            if name == "edit":
                return await self._edit_file(args)
            if name == "bash":
                return await self._bash(args)
            if name == "memory_save":
                return await self._memory_save(args)
            if name == "memory_search":
                return await self._memory_search(args)
            if name in self.extensions.tools:
                value = await self.extensions.call_tool(name, args)
                return value
            if name.startswith(f"{DEFAULT_MCP_PREFIX}"):
                value = await self.mcp_client.call(name, args)
                return value

            raise RuntimeError(f"Unknown tool '{name}'")
        except Exception as exc:  # pragma: no cover
            msg = f"{type(exc).__name__}: {exc}"
            await self.storage.log_event("tool_call.error", payload={"name": name, "error": msg}, level="error")
            if emit is not None:
                emit(ChatEvent("tool_error", msg))
            return msg

    async def chat(self, message: str, session_id: str | None = None, stream: bool = True, emitter=None) -> str:
        if session_id is None:
            session_id = await self.storage.ensure_active_session()
        await self.storage.add_message(session_id, "user", message)

        bootstrap = not await self.storage.get_bootstrap_state()
        agent = self._build_agent(bootstrap)

        context = await self._build_context(session_id, message)

        events: list[ChatEvent] = []

        class Emitter:
            def __init__(self, cb: Any) -> None:
                self.cb = cb

            def emit(self, event: ChatEvent) -> None:
                if self.cb is not None:
                    self.cb(event)

        deps = type("RuntimeContext", (), {"emit": None})()
        deps.emit = Emitter(emitter).emit if emitter is not None else (lambda event: None)

        # Attach helper for tool event callbacks.
        if emitter is not None:
            def _emit(event: ChatEvent) -> None:
                emitter(event)
            deps.emit = _emit

        result_output: str | None = None
        try:
            async with agent.run_stream_events(context, deps=deps) as stream_events:
                async for event in stream_events:
                    etype = type(event).__name__
                    if etype == "FunctionToolCallEvent":
                        if emitter is not None:
                            emitter(ChatEvent("model_tool_call", str(event)))
                    elif etype == "FunctionToolResultEvent":
                        if emitter is not None:
                            emitter(ChatEvent("model_tool_result", str(event)))
                    elif etype == "PartDeltaEvent":
                        delta = self._extract_text_delta(event)
                        if delta:
                            events.append(ChatEvent("assistant", delta))
                            if stream and emitter is not None:
                                emitter(ChatEvent("assistant_delta", delta))
                    elif etype == "FinalResultEvent":
                        result_output = str(event.result.output)

                if result_output is None:
                    # Fallback for API compatibility changes.
                    result = await agent.run(context, deps=deps)
                    result_output = str(result.output)

            if result_output is None:
                result_output = ""

            await self.storage.add_message(session_id, "assistant", result_output)
            return result_output
        finally:
            if bootstrap:
                await self.storage.set_bootstrap_complete(await self.storage.get_bootstrap_state())
            if emitter is not None:
                for event in events:
                    emitter(event)

    async def _build_context(self, session_id: str, user_message: str) -> str:
        profile = await self.storage.all_profile_fields()
        memories = await self.storage.memory_search(user_message, limit=DEFAULT_MEMORY_TOP_N)
        messages = await self.storage.get_recent_messages(session_id, 20)
        soul = await self._read_soul()
        summary_lines: list[str] = []

        summary_lines.append("Current message from user:")
        summary_lines.append(user_message)
        summary_lines.append("")
        summary_lines.append("Agent profile:")
        for key, value in profile.get("agent", {}).items():
            summary_lines.append(f"- {key}: {value}")
        summary_lines.append("User profile:")
        for key, value in profile.get("user", {}).items():
            summary_lines.append(f"- {key}: {value}")

        summary_lines.append("Recent memory:")
        for memory in memories:
            summary_lines.append(f"[{memory.id}] {memory.content}")

        summary_lines.append("Session context:")
        for message in messages:
            summary_lines.append(f"{message.role}: {message.content}")

        if soul:
            summary_lines.append("SOUL:")
            summary_lines.append(soul)

        tool_names = await self.list_tools()
        summary_lines.append("Available tools:")
        for tool in tool_names:
            summary_lines.append(f"- {tool}")

        summary_lines.append("\nUse the `tool_call` tool for all filesystem, memory, shell, and extension operations.")

        return "\n".join(summary_lines)

    async def _read_soul(self) -> str:
        soul = self.workspace / SOUL_FILE
        if not soul.exists():
            return ""
        return soul.read_text(encoding="utf-8")

    def _system_prompt(self, bootstrap: bool) -> str:
        if bootstrap:
            return """
You are pith. You have not finished bootstrap mode.
Before normal operation, collect agent and user profile fields in SQLite.
Required agent fields: name, nature.
Required user fields: name.
Persist completed bootstrap fields into profile records with tool calls and return compact confirmations.
Stay terse and safe.
"""
        return """
You are pith, a compact assistant that can reason and use tools via tool_call.
Use tools for file, shell, and memory operations.
Keep responses actionable and concise.
Never fabricate tool outputs.
"""

    async def _read_file(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        if not path:
            return "missing required arg: path"
        target = self._resolve_workspace_path(path)
        return target.read_text(encoding="utf-8")

    async def _write_file(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            return "missing required args: path, content"
        target = self._resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return f"written {target}"

    async def _edit_file(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        old = args.get("old")
        new = args.get("new")
        if not path or old is None or new is None:
            return "missing required args: path, old, new"
        target = self._resolve_workspace_path(path)
        text = target.read_text(encoding="utf-8")
        if str(old) not in text:
            return "old content not found"
        text = text.replace(str(old), str(new), 1)
        target.write_text(text, encoding="utf-8")
        return f"edited {target}"

    async def _bash(self, args: dict[str, Any]) -> str:
        command = args.get("command")
        if not command:
            return "missing required arg: command"

        cmd = str(command)
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DEFAULT_TOOL_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            return "command timed out"

        output = (stdout or b"").decode("utf-8", errors="replace")
        if len(output) > DEFAULT_MAX_TOOL_OUTPUT_CHARS:
            output = output[:DEFAULT_MAX_TOOL_OUTPUT_CHARS] + "..."
        return output.strip() if output else ""

    async def _memory_save(self, args: dict[str, Any]) -> str:
        content = args.get("content")
        if not content:
            return "missing required arg: content"
        kind = args.get("kind", "durable")
        tags = args.get("tags")
        source = args.get("source", "tool")
        if isinstance(tags, list):
            norm_tags = [str(x) for x in tags]
        elif tags:
            norm_tags = [str(tags)]
        else:
            norm_tags = []
        memory_id = await self.storage.memory_save(str(content), kind=kind, tags=norm_tags, source=source)
        return f"memory_saved:{memory_id}"

    async def _memory_search(self, args: dict[str, Any]) -> str:
        query = args.get("query")
        if not query:
            return "missing required arg: query"
        limit = int(args.get("limit", 8))
        records = await self.storage.memory_search(str(query), limit=limit)
        if not records:
            return "[]"
        payload = [
            {
                "id": rec.id,
                "content": rec.content,
                "kind": rec.kind,
                "tags": rec.tags,
                "source": rec.source,
            }
            for rec in records
        ]
        return json.dumps(payload)

    async def compact_session(self, session_id: str | None = None, keep: int = 50) -> str:
        if session_id is None:
            session_id = await self.storage.ensure_active_session()
        await self.storage.compact_session(session_id, keep_recent=keep)
        return f"compacted session {session_id}"

    async def new_session(self) -> str:
        return await self.storage.new_session()

    async def get_info(self, session_id: str | None = None) -> str:
        if session_id is None:
            session_id = await self.storage.ensure_active_session()
        bootstrap = await self.storage.get_bootstrap_state()
        profiles = await self.storage.all_profile_fields()
        messages = await self.storage.get_recent_messages(session_id, 5)
        return json.dumps(
            {
                "session_id": session_id,
                "bootstrap_complete": bootstrap,
                "agent_profile": profiles.get("agent", {}),
                "user_profile": profiles.get("user", {}),
                "message_count": len(messages),
            },
            indent=2,
            sort_keys=True,
        )

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            candidate = candidate
        else:
            candidate = self.workspace / candidate
        return candidate

    def _extract_text_delta(self, event: Any) -> str:
        if hasattr(event, "part"):
            part = event.part
            if hasattr(part, "content") and isinstance(part.content, str):
                return part.content
            if hasattr(part, "text") and isinstance(part.text, str):
                return part.text
        if hasattr(event, "text") and isinstance(event.text, str):
            return event.text
        return ""


class RuntimeContext:
    def __init__(self, emit):
        self.emit = emit
