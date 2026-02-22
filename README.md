# pith

A minimal, self-extending personal AI agent. Async Python, runs locally or in a container.

See [SPEC.md](SPEC.md) for full design.

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pith setup   # interactive — picks provider, model, API key
uv run pith chat    # streaming terminal chat
```

## Commands

- `pith setup` — interactive first-time configuration (writes `config.yaml` and `.env`)
- `pith chat` — interactive streaming terminal chat
- `pith run` — long-running service loop (Telegram bot if token is set, otherwise idle)
- `pith doctor` — print runtime status
- `pith logs tail` — stream event log

All commands are run via `uv run pith <command>`.

## Docker (optional)

A Dockerfile is included for containerized deployment. The container expects a volume-mounted workspace with `config.yaml` and `.env` already present (run `pith setup` locally first).

```bash
docker build -t pith .
docker run --env-file .env -v "$PWD:/workspace" -w /workspace pith
```

## Dependencies

- `uv` — environment and dependency management
- `pydantic-ai` — model orchestration
- `aiosqlite` — persistence
- `httpx` — HTTP client
- `prompt-toolkit` — terminal input
