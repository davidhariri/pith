# pith

A minimal, self-extending personal AI agent. Async Python, runs in a container.

See [SPEC.md](SPEC.md) for the full design.

## Tooling

- `uv` for Python environment and dependency management
- `ruff` for linting and formatting

## Development

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format .
```
