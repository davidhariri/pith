# pith

A minimal, self-extending personal AI agent. Async Python, runs in a container.

See [SPEC.md](SPEC.md) for full design.

## Quick setup

```bash
./scripts/install.sh
```

`pith setup` writes starter config in `~/.config/pith/config.yaml` and workspace `.env` template.

## Commands

- `pith setup` create or refresh local config/env templates
- `pith chat` interactive streaming terminal chat
- `pith run` start telegram polling channel
- `pith doctor` print runtime status
- `pith logs tail` stream event log

## Dependencies

- `uv` for dependency and script execution
- `ruff` for lint/format
- `pydantic-ai` model orchestration
- `aiosqlite` persistence
- `httpx` I/O

## Notes

- MCP tools are loaded from external config and called through the unified `tool_call` API.
- Tool names beginning with `MCP__` are reserved for MCP tools.
- Extension tools in `extensions/tools` must be named without that prefix.
