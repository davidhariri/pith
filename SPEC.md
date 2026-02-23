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
       │   Extension      │  ← autostarted channel tasks (e.g. telegram)
       │   channels       │
       └──────────────────┘
```

`pith run` is a long-running server that owns the Runtime and exposes it via HTTP/SSE. Out-of-process clients (like `pith chat`) connect over HTTP. Extension channels (like Telegram) are autostarted as asyncio tasks alongside the HTTP server.

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

- Core channel: CLI TUI (in-process, connects via HTTP).
- Extension channels follow `connect()`, `recv()`, `send()` contract.
- Extension channels are autostarted by `pith run` — each loaded channel gets an asyncio task that calls connect, then loops recv/send.
- The CLI TUI stays as a separate client so extension bugs cannot sever the primary control path.

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
- `tool_call` (catch-all for extension tools)

Each built-in tool is registered individually with typed parameters and descriptions. The model sees proper schemas for each. `tool_call` is only used for dynamically-loaded extension tools.

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
- Workspace is seeded with example extensions (telegram channel, web_fetch tool) on first run.

See `docs/decisions/003-extension-interface.md` and `docs/decisions/005-autonomy-boundary.md`.

**6. MCP servers (agent-installable)**

The agent can install MCP (Model Context Protocol) servers to discover and call third-party tools via HTTP. Configs live in the workspace:

```
workspace/mcp/
├── slack.yaml
└── github.yaml
```

Each yaml file defines one server:

```yaml
url: https://mcp.example.com/rpc
headers:
  Authorization: Bearer ${SOME_TOKEN}
```

- HTTP (streamable) transport only — no stdio/subprocess.
- Tool names are namespaced: `mcp_<server>_<tool>` (e.g. `mcp_slack_send_message`).
- On `refresh()`, each server's tools are discovered via JSON-RPC `tools/list`.
- Non-fatal discovery: unreachable servers are warned and skipped.
- Env var substitution in yaml values (`${VAR_NAME}`).
- MCP tools are called via the same `tool_call` built-in as extension tools.

**7. Memory system**

Canonical memory is DB-native in SQLite.

- `memory_save` persists memory entries directly in SQLite.
- `memory_search` queries SQLite FTS5 and returns full matched memory entries with metadata.
- Per turn, top ranked memory entries are injected into context.
- Session history is also persisted in SQLite for continuity and compaction.

See `docs/decisions/002-system-prompt.md`, `docs/decisions/006-memory-lifecycle-recall.md`, and `docs/decisions/007-session-compaction.md`.

**8. Identity and persona model**

- `SOUL.md` is always injected and remains agent-editable.
- Agent identity and user identity are stored in runtime-managed SQLite profile tables.
- Profile records are writable during bootstrap, then guarded and updated only on explicit user direction.

See `docs/decisions/011-bootstrap-profile-state.md` and `docs/decisions/005-autonomy-boundary.md`.

**9. Model runtime**

`pydantic-ai` is the compatibility layer for model providers and tool-calling.

See `docs/decisions/010-model-adapter.md`.

**10. Container boundary**

Docker is available for containerized deployment but not required. The agent's workspace is a `workspace/` subdirectory, separate from the pith source code. When running locally, basic path sandboxing constrains file access to this workspace directory. When running in Docker, the container provides additional process-level isolation.

- Workspace isolation: the agent sees only `workspace/` — pith source code (src/, tests/, docs/) is invisible.
- Path sandboxing: all file tools resolve paths relative to workspace and reject escapes.
- Docker (optional): workspace mount read/write, no host FS access beyond mounted paths, no Docker socket mount.
- External runtime config is outside workspace paths.
- Paths are derived from the config file location, not configurable: `<config_dir>/workspace/` for workspace, `<config_dir>/memory.db` for the database (outside workspace), `<config_dir>/workspace/.pith/logs/` for logs.

See `docs/decisions/004-container-runtime.md`, `docs/decisions/008-tool-execution-safety.md`, and `docs/decisions/012-external-config.md`.

**11. Observability**

Minimal structured audit trail:

- Append-only JSONL events for turns, tool calls, memory retrieval, profile updates, and extension reload failures.
- Keep logs local and simple.

See `docs/decisions/009-observability.md`.

**12. Interaction surfaces**

- CLI surface: `pith setup`, `pith run`, `pith chat`, `pith doctor`, `pith status`, `pith stop`, `pith restart`, `pith logs tail`.
- `pith run` starts the HTTP API server (Starlette + uvicorn) and autostarts any loaded extension channels. It owns the Runtime.
- `pith chat` connects to the running server via HTTP/SSE. It is the primary operator interface: interactive TUI with streaming assistant output.
- `pith chat` shows live runtime states and tool-call events while a turn is executing.
- Extension channels (e.g. Telegram) are autostarted as asyncio tasks and provide concise text responses.
- Both CLI chat and extension channels support slash commands: `/new`, `/compact`, `/info`.
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
- Not a heavy orchestration framework.
