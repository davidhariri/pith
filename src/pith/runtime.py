"""Core agent loop and tool dispatch."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import textwrap
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pydantic_monty
from pydantic_ai import Agent
from pydantic_ai._agent_graph import CallToolsNode, ModelRequestNode
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
)

from .config import Config
from .constants import (
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    DEFAULT_MEMORY_TOP_N,
    SOUL_FILE,
)
from .extensions import ExtensionRegistry
from .storage import Storage

SECRET_TIMEOUT = 60


class Runtime:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        extensions: ExtensionRegistry,
    ) -> None:
        self.cfg = cfg
        self.storage = storage
        self.extensions = extensions
        self.workspace = Path(cfg.runtime.workspace_path)
        self.log_dir = Path(cfg.runtime.log_dir)
        self.log_path = self.log_dir / "events.jsonl"
        self.storage.log_path = self.log_path
        self.agent: Agent[None, str] | None = None
        self._pending_secrets: dict[str, asyncio.Event] = {}
        self._secret_values: dict[str, str] = {}
        self._on_secret_request: Callable[[str, str], Awaitable[None]] | None = None

    @property
    def env_path(self) -> Path:
        return Path(self.cfg.runtime.workspace_path).parent / ".env"

    def provide_secret(self, request_id: str, value: str) -> None:
        """Deliver a secret value from the client and unblock the waiting tool."""
        self._secret_values[request_id] = value
        event = self._pending_secrets.get(request_id)
        if event:
            event.set()

    async def initialize(self) -> None:
        await self.storage.ensure_schema()
        await self.extensions.refresh()
        await self._ensure_bootstrap_state()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_bootstrap_state(self) -> None:
        complete = await self.storage.get_bootstrap_state()
        await self.storage.set_bootstrap_complete(complete)
        if not complete:
            await self.storage.set_app_state("bootstrap_note", "identity not fully configured")

    # -- Agent construction --

    def _build_agent(
        self, bootstrap: bool, model: Any = None, channel: str | None = None
    ) -> Agent[None, str]:
        model = model or f"{self.cfg.model.provider}:{self.cfg.model.model}"
        agent: Agent[None, str] = Agent(model, output_type=str)
        self._register_system_prompt(agent, bootstrap, channel)
        self._register_tools(agent, bootstrap)
        self.agent = agent
        return agent

    def _register_system_prompt(
        self, agent: Agent[None, str], bootstrap: bool, channel: str | None = None
    ) -> None:
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
                    textwrap.dedent(f"""\
                    ## Guidelines
                    - Always speak in first person. You ARE \
                    {agent_name} — never refer to yourself \
                    in third person.
                    - Be conversational and natural. \
                    You're a thinking partner, not a \
                    command executor.
                    - Be action-oriented. When asked to do \
                    something, try it. Don't hedge about \
                    what you can or can't do — use your \
                    tools and find out. If something fails, \
                    try a different approach. Exhaust your \
                    own options before asking the user for \
                    help. Never present a menu of options \
                    when you could just try the most \
                    likely one.
                    - You can extend yourself. If you need \
                    a capability you don't have, build it — \
                    write an extension tool, install an MCP \
                    server, or use web_fetch to research \
                    an API. You have the tools to grow \
                    your own abilities. Do it, don't ask \
                    permission.
                    - When you need an API key or secret: \
                    first call list_secrets to check what's \
                    available, then call store_secret with \
                    just the key name. The user will be \
                    prompted securely — you never see the \
                    value. IMPORTANT: when calling \
                    store_secret, do NOT generate any \
                    accompanying text — just make the tool \
                    call alone and wait for the result. \
                    Never ask for secrets in chat.
                    - Never expose your own internals. \
                    Don't mention sandboxing, workspaces, \
                    tool names, system prompts, or how \
                    you work. Just act naturally.
                    - After completing a task, consider: \
                    could a tool, memory, or preference \
                    make this easier next time? If so, \
                    create it.
                    - Use tools when needed for file \
                    and memory operations. Use run_python \
                    when you need to compute something.
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

            # Extension tool list (for awareness, not schemas)
            ext_tools = sorted(runtime.extensions.tools.keys())
            mcp_tools = runtime.extensions.mcp.get_tool_descriptions()
            if ext_tools or mcp_tools:
                extra_lines = ["# Additional tools (call via tool_call)"]
                for t in ext_tools:
                    extra_lines.append(f"- {t}")
                for t, desc in sorted(mcp_tools.items()):
                    line = f"- {t}"
                    if desc:
                        line += f": {desc}"
                    extra_lines.append(line)
                parts.append("\n".join(extra_lines))

            if channel:
                parts.append(f"# Channel\n{channel}")

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

        @agent.tool_plain(
            description=(
                "List files and directories at a workspace path. "
                "Returns one entry per line. Use glob to filter "
                "(e.g. '*.py'). Non-recursive by default."
            )
        )
        async def list_dir(
            path: str = ".", glob: str | None = None, recursive: bool = False
        ) -> str:
            """List directory contents, optionally filtered by glob pattern."""
            target = runtime._resolve_workspace_path(path)
            if not target.is_dir():
                return f"not a directory: {path}"
            ws_root = runtime.workspace.resolve()
            if recursive:
                entries = sorted(target.rglob("*"))
            else:
                entries = sorted(target.iterdir())
            lines: list[str] = []
            for entry in entries:
                rel = str(entry.relative_to(ws_root))
                if glob and not fnmatch.fnmatch(entry.name, glob):
                    continue
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{rel}{suffix}")
            output = "\n".join(lines)
            if len(output) > DEFAULT_MAX_TOOL_OUTPUT_CHARS:
                output = output[:DEFAULT_MAX_TOOL_OUTPUT_CHARS] + "\n..."
            return output or "(empty)"

        @agent.tool_plain(
            description=(
                "Search file contents for a pattern (regex or literal). "
                "Searches workspace files matching the optional glob filter. "
                "Returns matching lines with file path and line number."
            )
        )
        async def file_search(
            pattern: str,
            glob: str = "*",
            recursive: bool = True,
            literal: bool = False,
            max_results: int = 50,
        ) -> str:
            """Grep-like search across workspace files."""
            ws_root = runtime.workspace.resolve()
            if literal:
                regex = re.compile(re.escape(pattern))
            else:
                try:
                    regex = re.compile(pattern)
                except re.error as exc:
                    return f"invalid regex: {exc}"
            matches: list[str] = []
            if recursive:
                files = sorted(ws_root.rglob(glob))
            else:
                files = sorted(ws_root.glob(glob))
            for filepath in files:
                if not filepath.is_file():
                    continue
                # Skip binary / non-text files
                try:
                    text = filepath.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError):
                    continue
                rel = str(filepath.relative_to(ws_root))
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{rel}:{lineno}: {line}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if not matches:
                return "no matches"
            output = "\n".join(matches)
            if len(output) > DEFAULT_MAX_TOOL_OUTPUT_CHARS:
                output = output[:DEFAULT_MAX_TOOL_OUTPUT_CHARS] + "\n..."
            return output

        @agent.tool_plain(
            description=(
                "Run Python code in a sandboxed interpreter. "
                "Has access to read(path), write(path, content), edit(path, old, new) "
                "functions for file operations. No filesystem, network, or import access "
                "beyond these functions. Returns the final expression value or printed output."
            )
        )
        async def run_python(code: str) -> str:
            """Execute Python code safely via Monty."""

            def _host_read(path: str) -> str:
                target = runtime._resolve_workspace_path(path)
                return target.read_text(encoding="utf-8")

            def _host_write(path: str, content: str) -> str:
                target = runtime._resolve_workspace_path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return f"written {target}"

            def _host_edit(path: str, old: str, new: str) -> str:
                target = runtime._resolve_workspace_path(path)
                text = target.read_text(encoding="utf-8")
                if old not in text:
                    return "old content not found"
                text = text.replace(old, new, 1)
                target.write_text(text, encoding="utf-8")
                return f"edited {target}"

            external_fns = {
                "read": _host_read,
                "write": _host_write,
                "edit": _host_edit,
            }

            try:
                m = pydantic_monty.Monty(
                    code,
                    external_functions=list(external_fns.keys()),
                    script_name="agent.py",
                )

                # Iterative execution: handle external function calls
                result = m.start()
                while result.function_name is not None:
                    fn = external_fns.get(result.function_name)
                    if fn is None:
                        msg = f"unknown function: {result.function_name}"
                        result = result.resume(return_value=msg)
                        continue
                    try:
                        ret = fn(*result.args, **result.kwargs)
                    except Exception as exc:
                        ret = f"{type(exc).__name__}: {exc}"
                    result = result.resume(return_value=ret)

                output = result.output or ""
            except pydantic_monty.MontyError as exc:
                output = f"MontyError: {exc}"
            except Exception as exc:
                output = f"{type(exc).__name__}: {exc}"

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
                if name in runtime.extensions.mcp.tools:
                    return await runtime.extensions.mcp.call(name, call_args)
                return f"unknown tool: {name}"
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                await runtime.storage.log_event(
                    "tool_call.error", payload={"name": name, "error": msg}, level="error"
                )
                return msg

        @agent.tool_plain(
            description=(
                "List the names of stored secrets (environment variables from .env). "
                "Returns only key names, never values."
            )
        )
        async def list_secrets() -> str:
            """Return the names of secrets stored in .env."""
            env_path = runtime.env_path
            if not env_path.exists():
                return "[]"
            names: list[str] = []
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key:
                    names.append(key)
            return json.dumps(names)

        @agent.tool_plain(
            description=(
                "Store a secret (API key, token, etc). Prompts the user to enter the "
                "value securely — you will never see the value. Only provide the key name."
            )
        )
        async def store_secret(name: str) -> str:
            """Request a secret value from the user and store it in .env."""
            if runtime._on_secret_request is None:
                return (
                    "error: non-interactive session — ask the user to set this secret via the CLI"
                )

            request_id = uuid.uuid4().hex[:12]
            event = asyncio.Event()
            runtime._pending_secrets[request_id] = event

            try:
                await runtime._on_secret_request(request_id, name)
                try:
                    await asyncio.wait_for(event.wait(), timeout=SECRET_TIMEOUT)
                except TimeoutError:
                    return "error: timed out waiting for secret input"

                value = runtime._secret_values.pop(request_id, "")
                if not value:
                    return "error: no value provided"

                # Write to .env
                env_path = runtime.env_path
                env_path.parent.mkdir(parents=True, exist_ok=True)
                lines: list[str] = []
                replaced = False
                if env_path.exists():
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and "=" in stripped:
                            key = stripped.split("=", 1)[0].strip()
                            if key == name:
                                lines.append(f"{name}={value}")
                                replaced = True
                                continue
                        lines.append(line)
                if not replaced:
                    lines.append(f"{name}={value}")
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

                # Set in current process
                os.environ[name] = value
                return f"stored secret '{name}'"
            finally:
                runtime._pending_secrets.pop(request_id, None)
                runtime._secret_values.pop(request_id, None)

    # -- Chat --

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, bool], None] | None = None,
        on_secret_request: Callable[[str, str], Awaitable[None]] | None = None,
        channel: str | None = None,
    ) -> str:
        self._on_secret_request = on_secret_request
        if session_id is None:
            session_id = await self.storage.ensure_active_session()

        bootstrap = not await self.storage.get_bootstrap_state()
        agent = self._build_agent(bootstrap, channel=channel)

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
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
                            if isinstance(event, FunctionToolCallEvent):
                                if on_tool_call:
                                    args = event.part.args
                                    if isinstance(args, str):
                                        try:
                                            args = json.loads(args)
                                        except (json.JSONDecodeError, ValueError):
                                            args = {"raw": args}
                                    on_tool_call(event.part.tool_name, args or {})
                            elif isinstance(event, FunctionToolResultEvent):
                                if on_tool_result:
                                    success = not isinstance(event.result, RetryPromptPart)
                                    on_tool_result(event.result.tool_name or "unknown", success)

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
