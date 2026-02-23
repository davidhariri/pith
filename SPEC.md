# pith

A minimal, self-extending personal AI agent. Async Python, optionally containerized.

## Philosophy

- **Small core, agent-grown capabilities.** The system ships with the minimum needed to think, remember, communicate, and extend itself.
- **Auditable.** A human should be able to read the whole core quickly.
- **Container-first safety boundary.** The container is the primary sandbox.
- **SQLite-native continuity.** Memory and session history are stored in SQLite as the single source of truth.
- **Split control planes.** Runtime/integration config lives outside workspace; agent-editable artifacts live inside workspace.

## Design Targets

- **Power:** Agent can self-create and self-edit extensions at runtime.
- **Safety:** Agent has broad freedom inside the container, but no access outside mounted boundaries.
- **Elegance:** Keep fewer moving parts and fewer lines than OpenClaw-style stacks.
- **Deterministic onboarding:** Bootstrap mode is runtime-controlled, not file-deletion-driven.

## Architecture

```
┌─────────────┐     ┌─────────────┐
│  pith chat   │     │  future web  │
│  (terminal)  │     │  client      │
└──────┬───────┘     └──────┬───────┘
       │  HTTP/SSE          │  HTTP/SSE
       └────────┬───────────┘
                │
       ┌────────▼────────┐
       │   pith run       │  ← Starlette + uvicorn
       │   (HTTP server)  │
       │                  │
       │   ┌──────────┐   │
       │   │ Runtime   │   │
       │   │ Storage   │   │
       │   └──────────┘   │
       │                  │
       │   Telegram task  │  ← direct Runtime access (in-process)
       └──────────────────┘
```

`pith run` is a long-running server that owns the Runtime and exposes it via HTTP/SSE. Out-of-process clients (like `pith chat`) connect over HTTP. Telegram stays in-process with direct Runtime access.

## Components

**1. Agent runtime**

Receives messages, assembles context, calls model, executes tool calls, replies.

- Uses `pydantic-ai` for model/tool orchestration and provider compatibility.
- Async Python throughout.

**2. Prompt and bootstrap state machine**

Prompt mode is selected by core runtime state in SQLite:

- **Bootstrap mode** when required profile fields are missing.
- **Normal mode** when bootstrap is complete.

Bootstrap completion is set by runtime validation, not by asking the agent to delete a file.

See `docs/decisions/011-bootstrap-profile-state.md`.

**3. Channels**

- Core channels: CLI TUI and Telegram.
- Extension channels follow `connect()`, `recv()`, `send()`.
- Both core channels stay in runtime so extension bugs cannot sever control paths.

See `docs/decisions/001-telegram-polling.md` and `docs/decisions/003-extension-interface.md`.

**4. Built-in tools**

- `read`
- `write`
- `edit`
- `list_dir`
- `file_search`
- `run_python`
- `memory_save`
- `memory_search`
- `set_profile`
- `tool_call` (catch-all for extension and MCP tools)

Each built-in tool is registered individually with typed parameters and descriptions. The model sees proper schemas for each. `tool_call` is only used for dynamically-loaded extension and MCP tools.

Tool surface stays intentionally small. Growth comes from agent-authored extension tools.

**5. Extension system (self-growth)**

File system is the registry:

```
workspace/extensions/
├── tools/
└── channels/
```

- One file = one extension unit.
- Tools expose `async def run(...)`.
- Channels expose `connect/recv/send`.
- Extensions are hot-reloaded.
- Tool names under `extensions/tools/` may not start with reserved prefix `MCP__`.
- Runtime rejects extension tools using reserved prefixes to prevent namespace collisions.

See `docs/decisions/003-extension-interface.md` and `docs/decisions/005-autonomy-boundary.md`.

**6. Memory system**

Canonical memory is DB-native in SQLite.

- `memory_save` persists memory entries directly in SQLite.
- `memory_search` queries SQLite FTS5 and returns full matched memory entries with metadata.
- Per turn, top ranked memory entries are injected into context.
- Session history is also persisted in SQLite for continuity and compaction.

See `docs/decisions/002-system-prompt.md`, `docs/decisions/006-memory-lifecycle-recall.md`, and `docs/decisions/007-session-compaction.md`.

**7. Identity and persona model**

- `SOUL.md` is always injected and remains agent-editable.
- Agent identity and user identity are stored in runtime-managed SQLite profile tables.
- Profile records are writable during bootstrap, then guarded and updated only on explicit user direction.

See `docs/decisions/011-bootstrap-profile-state.md` and `docs/decisions/005-autonomy-boundary.md`.

**8. MCP client**

Calls external MCP tools (stdio or HTTP). MCP server definitions come from external `config.yaml` outside workspace.

- Runtime reads config from `PITH_CONFIG` or default host path `~/.config/pith/config.yaml`.
- In Docker, this config is mounted read-only (for example `/run/pith/config.yaml`).
- Config is runtime-owned and not agent-autonomous state.
- Model/provider configuration is also loaded from this external config.
- API secrets are loaded from `.env`/environment variables referenced by config.
- MCP tools are exposed in runtime tool namespace as `MCP__<server>__<tool>`.
- Extension and MCP tools are called via the `tool_call(name, args)` catch-all tool.

**9. Model runtime**

`pydantic-ai` is the compatibility layer for model providers and tool-calling.

See `docs/decisions/010-model-adapter.md`.

**10. Container boundary**

Docker is available for containerized deployment but not required. The agent's workspace is a `workspace/` subdirectory, separate from the pith source code. When running locally, basic path sandboxing constrains file access to this workspace directory. When running in Docker, the container provides additional process-level isolation.

- Workspace isolation: the agent sees only `workspace/` — pith source code (src/, tests/, docs/) is invisible.
- Path sandboxing: all file tools resolve paths relative to workspace and reject escapes.
- Docker (optional): workspace mount read/write, no host FS access beyond mounted paths, no Docker socket mount.
- External runtime config is outside workspace paths.

See `docs/decisions/004-container-runtime.md`, `docs/decisions/008-tool-execution-safety.md`, and `docs/decisions/012-external-config.md`.

**11. Observability**

Minimal structured audit trail:

- Append-only JSONL events for turns, tool calls, memory retrieval, profile updates, and extension reload failures.
- Keep logs local and simple.

See `docs/decisions/009-observability.md`.

**12. Interaction surfaces**

- CLI surface: `pith setup`, `pith run`, `pith chat`, `pith doctor`, `pith status`, `pith stop`, `pith restart`, `pith logs tail`.
- `pith run` starts the HTTP API server (Starlette + uvicorn) and optionally Telegram. It owns the Runtime.
- `pith chat` connects to the running server via HTTP/SSE. It is the primary operator interface: interactive TUI with streaming assistant output.
- `pith chat` shows live runtime states and tool-call events while a turn is executing.
- Telegram is intentionally limited UX: concise text responses and no full live event stream.
- Both CLI chat and Telegram support slash commands: `/new`, `/compact`, `/info`.
- Slash commands are handled before model invocation and do not require tool calls.
- `/new` starts a new session, `/compact` compacts current session history, `/info` shows runtime/session status.

See `docs/decisions/014-interaction-surfaces-and-slash-commands.md`.

## Runtime

- Python 3.12+
- `pydantic-ai`
- `aiosqlite`
- `httpx`
- `prompt-toolkit`
- `starlette` + `uvicorn` (HTTP API server)

## Developer Tooling

- `uv` for dependency management, virtualenv management, and command execution
- `ruff` for linting and formatting

## Context Assembly Per Turn

1. Fixed system prompt (bootstrap or normal, selected by runtime state)
2. `SOUL.md` (always injected)
3. Agent/user profile summary from SQLite
4. Relevant full memory entries from SQLite FTS5 index
5. Conversation history window
6. New message

## What this is NOT

- Not multi-tenant.
- Not a plugin marketplace.
- Not an MCP server.
- Not a heavy orchestration framework.
