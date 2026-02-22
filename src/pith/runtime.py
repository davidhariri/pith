"""Core agent loop and tool dispatch."""

from __future__ import annotations

import asyncio
import json
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai._agent_graph import CallToolsNode, ModelRequestNode
from pydantic_ai.messages import (
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)

from .config import Config
from .constants import (
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    DEFAULT_MCP_PREFIX,
    DEFAULT_MEMORY_TOP_N,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    SOUL_FILE,
)
from .extensions import ExtensionRegistry
from .mcp_client import MCPClient
from .storage import Storage


class Runtime:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        extensions: ExtensionRegistry,
        mcp_client: MCPClient,
    ) -> None:
        self.cfg = cfg
        self.storage = storage
        self.extensions = extensions
        self.mcp_client = mcp_client
        self.workspace = Path(cfg.runtime.workspace_path)
        self.log_dir = Path(cfg.runtime.log_dir)
        self.log_path = self.log_dir / "events.jsonl"
        self.storage.log_path = self.log_path
        self.agent: Agent[None, str] | None = None

    async def initialize(self) -> None:
        await self.storage.ensure_schema()
        await self.extensions.refresh()
        await self.mcp_client.discover()
        for warning in self.mcp_client.discovery_warnings:
            print(f"\033[0;33m[warn][non-fatal]\033[0m {warning}")
            await self.storage.log_event(
                "mcp.discovery.warning", level="warning", payload={"message": warning}
            )
        await self._ensure_bootstrap_state()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_bootstrap_state(self) -> None:
        complete = await self.storage.get_bootstrap_state()
        await self.storage.set_bootstrap_complete(complete)
        if not complete:
            await self.storage.set_app_state("bootstrap_note", "identity not fully configured")

    # -- Agent construction --

    def _build_agent(self, bootstrap: bool, model: Any = None) -> Agent[None, str]:
        model = model or f"{self.cfg.model.provider}:{self.cfg.model.model}"
        agent: Agent[None, str] = Agent(model, output_type=str)
        self._register_system_prompt(agent, bootstrap)
        self._register_tools(agent, bootstrap)
        self.agent = agent
        return agent

    def _register_system_prompt(self, agent: Agent[None, str], bootstrap: bool) -> None:
        runtime = self  # capture for closure

        @agent.system_prompt
        async def build_system_prompt() -> str:
            parts: list[str] = []

            profiles = await runtime.storage.all_profile_fields()
            agent_profile = profiles.get("agent", {})
            user_profile = profiles.get("user", {})

            if bootstrap:
                parts.append(
                    textwrap.dedent("""\
                    You are pith — a new personal AI agent, \
                    just coming online for the first time.

                    Your job right now is to get to know your \
                    owner and figure out who you are together. \
                    This is a conversation, not an interrogation. \
                    Be warm, curious, and natural.

                    Discover these things one at a time \
                    (don't ask all at once):
                    - Agent name: What should they call you? \
                    (pith is the default, but they can pick anything)
                    - Agent nature: What kind of entity are you? \
                    (AI assistant is fine, but something more \
                    personal is encouraged)
                    - User name: What's their name?

                    Use the set_profile tool to save each field \
                    as you learn it \
                    (profile_type='agent'/'user', \
                    key='name'/'nature').

                    When you've collected all three, use the \
                    write tool to create a SOUL.md file that \
                    captures the vibe of the conversation — \
                    this becomes your personality going forward. \
                    Then tell them you're ready.

                    Start by introducing yourself and asking \
                    who they are.""")
                )
            else:
                agent_name = agent_profile.get("name", "pith")
                soul = runtime._read_soul()

                identity = f"You are {agent_name}, a personal AI agent."
                if user_profile.get("name"):
                    identity += f" Your user is {user_profile['name']}."
                parts.append(identity)

                if soul:
                    parts.append(soul)

                parts.append(
                    textwrap.dedent("""\
                    ## Guidelines
                    - Be conversational and natural. \
                    You're a thinking partner, not a \
                    command executor.
                    - Use tools when needed for file, \
                    shell, and memory operations.
                    - Never fabricate tool outputs.
                    - When a conversation starts, greet \
                    your user warmly and naturally.
                    - Keep responses concise but not \
                    robotic.""")
                )

            # Profiles (show remaining fields not already used in identity)
            if agent_profile or user_profile:
                profile_lines = ["# Profiles"]
                if agent_profile:
                    profile_lines.append("Agent:")
                    for k, v in agent_profile.items():
                        profile_lines.append(f"  {k}: {v}")
                if user_profile:
                    profile_lines.append("User:")
                    for k, v in user_profile.items():
                        profile_lines.append(f"  {k}: {v}")
                parts.append("\n".join(profile_lines))

            # Extension + MCP tool list (for awareness, not schemas)
            ext_tools = sorted(runtime.extensions.tools.keys())
            mcp_tools = runtime.mcp_client.list_tools()
            if ext_tools or mcp_tools:
                extra_lines = ["# Additional tools (call via tool_call)"]
                for t in ext_tools:
                    extra_lines.append(f"- {t}")
                for t in mcp_tools:
                    extra_lines.append(f"- {t}")
                parts.append("\n".join(extra_lines))

            return "\n\n".join(parts)

    def _register_tools(self, agent: Agent[None, str], bootstrap: bool) -> None:
        runtime = self  # capture for closures

        @agent.tool_plain(description="Read a file from the workspace.")
        async def read(path: str) -> str:
            """Read a file at the given workspace-relative path."""
            target = runtime._resolve_workspace_path(path)
            return target.read_text(encoding="utf-8")

        @agent.tool_plain(description="Write content to a file in the workspace.")
        async def write(path: str, content: str) -> str:
            """Write content to a file, creating parent directories as needed."""
            target = runtime._resolve_workspace_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"written {target}"

        @agent.tool_plain(description="Edit a file by replacing old text with new text.")
        async def edit(path: str, old: str, new: str) -> str:
            """Replace the first occurrence of old with new in the file."""
            target = runtime._resolve_workspace_path(path)
            text = target.read_text(encoding="utf-8")
            if old not in text:
                return "old content not found"
            text = text.replace(old, new, 1)
            target.write_text(text, encoding="utf-8")
            return f"edited {target}"

        @agent.tool_plain(description="Run a shell command in the workspace.")
        async def bash(command: str) -> str:
            """Execute a shell command and return its output."""
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=runtime.workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=DEFAULT_TOOL_TIMEOUT_SECONDS
                )
            except TimeoutError:
                proc.kill()
                return "command timed out"

            output = (stdout or b"").decode("utf-8", errors="replace")
            if len(output) > DEFAULT_MAX_TOOL_OUTPUT_CHARS:
                output = output[:DEFAULT_MAX_TOOL_OUTPUT_CHARS] + "..."
            return output.strip() if output else ""

        @agent.tool_plain(description="Save a memory entry for future recall.")
        async def memory_save(
            content: str, kind: str = "durable", tags: list[str] | None = None
        ) -> str:
            """Persist a memory entry in the database."""
            memory_id = await runtime.storage.memory_save(
                content, kind=kind, tags=tags, source="tool"
            )
            return f"memory_saved:{memory_id}"

        @agent.tool_plain(description="Search memory entries by query.")
        async def memory_search(query: str, limit: int = 8) -> str:
            """Search stored memories using FTS5 full-text search."""
            records = await runtime.storage.memory_search(query, limit=limit)
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

        @agent.tool_plain(description="Set a profile field for agent or user identity.")
        async def set_profile(profile_type: str, key: str, value: str) -> str:
            """Set a profile field. profile_type is 'agent' or 'user'."""
            if profile_type not in ("agent", "user"):
                return "profile_type must be 'agent' or 'user'"
            await runtime.storage.set_profile(profile_type, key, value)
            return f"profile_set:{profile_type}.{key}={value}"

        @agent.tool_plain(
            description="Call an extension or MCP tool by name. Use for tools not built-in."
        )
        async def tool_call(name: str, args: dict[str, Any] | None = None) -> str:
            """Route a call to an extension or MCP tool."""
            call_args = args or {}
            await runtime.storage.log_event(
                "tool_call.start", payload={"name": name, "args": call_args}
            )
            try:
                if name in runtime.extensions.tools:
                    return await runtime.extensions.call_tool(name, call_args)
                if name.startswith(DEFAULT_MCP_PREFIX):
                    return await runtime.mcp_client.call(name, call_args)
                return f"unknown tool: {name}"
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                await runtime.storage.log_event(
                    "tool_call.error", payload={"name": name, "error": msg}, level="error"
                )
                return msg

    # -- Chat --

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str], None] | None = None,
    ) -> str:
        if session_id is None:
            session_id = await self.storage.ensure_active_session()

        bootstrap = not await self.storage.get_bootstrap_state()
        agent = self._build_agent(bootstrap)

        # Load message history and inject top-N memory as context
        history = await self.storage.get_message_history(session_id)
        memories = await self.storage.memory_search(message, limit=DEFAULT_MEMORY_TOP_N)

        # Build user message with memory context if available
        user_text = message
        if memories:
            mem_lines = ["[Relevant memories]"]
            for m in memories:
                mem_lines.append(f"- {m.content}")
            user_text = "\n".join(mem_lines) + f"\n\n{message}"

        # Run agent with proper message history and streaming
        full_text: list[str] = []

        async with agent.iter(user_text, message_history=history) as run:
            async for node in run:
                if isinstance(node, ModelRequestNode):
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
                            is_start = isinstance(event, PartStartEvent) and isinstance(
                                event.part, TextPart
                            )
                            is_delta = isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            )
                            if is_start and event.part.content:
                                full_text.append(event.part.content)
                                if on_text:
                                    on_text(event.part.content)
                            elif is_delta:
                                delta = event.delta.content_delta
                                full_text.append(delta)
                                if on_text:
                                    on_text(delta)
                elif isinstance(node, CallToolsNode):
                    if on_tool and hasattr(node, "tool_name"):
                        on_tool(node.tool_name)

        # Persist all new messages from this run
        new_messages: list[ModelMessage] = run.result.new_messages()
        await self.storage.append_messages(session_id, new_messages)

        # Check bootstrap completion
        if bootstrap:
            await self.storage.set_bootstrap_complete(await self.storage.get_bootstrap_state())

        return "".join(full_text)

    # -- Session/info operations --

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
        messages = await self.storage.get_message_history(session_id, limit=5)
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

    async def refresh_extensions(self) -> None:
        await self.extensions.refresh()

    # -- Helpers --

    def _resolve_workspace_path(self, path: str) -> Path:
        resolved = (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace.resolve()):
            raise ValueError(f"path escapes workspace: {path}")
        return resolved

    def _read_soul(self) -> str:
        soul = self.workspace / SOUL_FILE
        if not soul.exists():
            return ""
        return soul.read_text(encoding="utf-8")
