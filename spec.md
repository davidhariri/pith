# pith

A minimal, self-extending personal AI agent. Async Python, runs in a container.

## Philosophy

- **Small core, agent-grown capabilities.** The system ships with the minimum needed to think, remember, and communicate. New capabilities are written by the agent itself at runtime and hot-reloaded.
- **Auditable.** A human should be able to read the entire core in one sitting.
- **Container-isolated.** The agent process runs inside a container. It can only affect the outside world through explicitly mounted paths and exposed channels.

## Architecture

```
Telegram ─┐
           ├─→ Channel Interface ─→ Agent (in container)
(future) ──┘         ↑                  ↓
                     │            ┌─────────────┐
                     │            │  Tools       │
                     │            │  - read      │
                     │            │  - write     │
                     │            │  - edit      │
                     │            │  - bash      │
                     │            │  - mcp_call  │
                     │            └─────────────┘
                     │                  ↓
                     │            Extensions (hot-reloaded)
                     │                  ↓
                     └─── Memory (SQLite) ──→ disk
```

### Components

**1. Agent runtime** — The core loop. Receives a message, builds context (conversation history + memory), calls a model, executes tool calls, returns a response. Async Python using `httpx` for model calls. No framework — just a loop.

**2. Channel interface** — Abstract base for messaging platforms. A channel receives messages from the outside world and delivers agent responses back. First implementation: Telegram (via Bot API). Channels are async generators — they yield incoming messages and accept outgoing ones.

**3. Tools** — The agent's hands. Minimal built-in set inspired by Pi:
- `read` — read a file
- `write` — write a file
- `edit` — edit a file (string replacement)
- `bash` — run a shell command (inside the container)
- `mcp_call` — call a tool on a connected MCP server

**4. Extensions** — Python modules the agent writes and the system hot-reloads. An extension can:
- Register new tools
- Register message hooks (pre/post processing)
- Persist state to disk within the agent's workspace

Extensions live in a known directory (e.g. `workspace/extensions/`). The system watches this directory and reloads on change. No registry, no manifest — drop a `.py` file, it gets loaded.

**5. Memory** — SQLite database for conversation history and agent knowledge. Simple key-value + full-text search. No vector embeddings in v1 — start with FTS5 and see if it's sufficient.

**6. MCP client** — Connects to configured MCP servers (stdio or HTTP transport). Exposes their tools to the agent via `mcp_call`. Configuration is a simple dict of server name → command/args.

**7. Container** — The agent process runs inside a Docker container. The container gets:
- Mounted workspace directory (extensions, memory db, agent-written files)
- Network access (for model API calls, Telegram API, MCP HTTP servers)
- No access to host filesystem beyond the workspace mount

## Runtime

- **Python 3.12+**, async throughout
- **uvicorn** — HTTP server for webhooks (Telegram webhook mode)
- **httpx** — async HTTP client for model API calls
- **aiosqlite** — async SQLite for memory
- No web framework (no FastAPI, no Flask). Raw ASGI app or just uvicorn with a simple router.

## What this is NOT

- Not a multi-tenant platform. One agent, one owner.
- Not a plugin marketplace. The agent writes its own extensions.
- Not an MCP server. It's an MCP client that can call tools on other servers.
- Not model-specific. Should work with any model that supports tool use (Claude, GPT, etc.) via a simple adapter.

## Open questions

- Webhook vs polling for Telegram? Webhook is cleaner but needs a public URL (or ngrok for dev).
- How should the agent's system prompt be managed? File on disk that the agent can edit?
- Should extensions have an explicit interface (e.g. `register()` function) or be fully convention-based (e.g. top-level `TOOLS = [...]`)?
- Container runtime: Docker only, or also support Apple Containers / Podman?
