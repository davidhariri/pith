# pith

A minimal, self-extending personal AI agent. Async Python, Docker-contained.

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
Telegram (core) ──┐
                   ├─→ Agent Loop ─→ Model Adapter
ext/channels/* ───┘        ↓
                     ┌───────────┐
                     │ Tools     │
                     │ - read    │
                     │ - write   │
                     │ - edit    │
                     │ - bash    │
                     │ - mcp_call│
                     │ - memory_save
                     │ - memory_search
                     │ + ext/*   │
                     └───────────┘
                          ↓
     SOUL.md + profiles/memory/sessions (SQLite + FTS5)
```

## Components

**1. Agent runtime**

Receives messages, assembles context, calls model, executes tool calls, replies. Async Python with `httpx`. No web framework.

**2. Prompt and bootstrap state machine**

Prompt mode is selected by core runtime state in SQLite:

- **Bootstrap mode** when required profile fields are missing.
- **Normal mode** when bootstrap is complete.

Bootstrap completion is set by runtime validation, not by asking the agent to delete a file.

See `docs/decisions/011-bootstrap-profile-state.md`.

**3. Channels**

- Core channel: Telegram.
- Extension channels follow `connect()`, `recv()`, `send()`.
- Telegram remains in core so extension bugs cannot sever the primary control path.

See `docs/decisions/001-telegram-polling.md` and `docs/decisions/003-extension-interface.md`.

**4. Built-in tools**

- `read`
- `write`
- `edit`
- `bash`
- `mcp_call`
- `memory_save`
- `memory_search`

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

**9. Model adapter**

Provider-agnostic interface with one canonical internal message/tool schema.

- Start with OpenAI-compatible tool-calling.
- Add adapters only when needed.

See `docs/decisions/010-model-adapter.md`.

**10. Container boundary**

Docker only. The agent runs with broad in-container freedom, constrained by mount and container isolation.

- Workspace mount read/write.
- No host FS access beyond mounted workspace.
- No Docker socket mount.
- External runtime config is mounted read-only and outside workspace paths.

See `docs/decisions/004-container-runtime.md`, `docs/decisions/008-tool-execution-safety.md`, and `docs/decisions/012-external-config.md`.

**11. Observability**

Minimal structured audit trail:

- Append-only JSONL events for turns, tool calls, memory retrieval, profile updates, and extension reload failures.
- Keep logs local and simple.

See `docs/decisions/009-observability.md`.

## Runtime

- Python 3.12+
- `uvicorn`
- `httpx`
- `aiosqlite`
- No web framework

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
