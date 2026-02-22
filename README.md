# pith

A minimal, self-extending personal AI agent. Async Python, runs in a container.

See [SPEC.md](SPEC.md) for full design.

## Quick start

From the repo root:

```bash
make run
```

`make run` bootstraps runtime files on first run:

- copies `config.example.yaml` to `./config.yaml` if missing
- copies `.env.example` to `.env` if missing
- prompts for basic first-time values in `.env` (API key required, Telegram optional)

Then it starts the Dockerized runtime.

If Docker is unavailable:

```bash
make risk
```

`make risk` runs without containerization (requires `uv`), useful for local/dev environments.

## Commands

- `make run` build image and run service in Docker (requires Docker)
- `make update` rebuild Docker image from scratch
- `make risk` run service without Docker (requires `uv`)
- `pith setup` create or refresh local config/env templates
- `pith chat` interactive streaming terminal chat
- `pith run` run service loop (Telegram optional if token is set)
- `pith doctor` print runtime status
- `pith logs tail` stream event log

## Dependencies

- `docker` for containerized default path (`make run`)
- `uv` for local runtime (`make risk`)
- `pydantic-ai` model orchestration
- `aiosqlite` persistence
- `httpx` I/O

## Build output

- Docker build logs are hidden by default for a cleaner startup UX.
- To show full Docker build logs, run with: `PITH_VERBOSE_BUILD=1 make run`

## Notes

- MCP tools are loaded from external config and called through the unified `tool_call` API.
- Tool names beginning with `MCP__` are reserved for MCP tools.
- Extension tools in `extensions/tools` must be named without that prefix.
