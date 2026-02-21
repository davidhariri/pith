# Agents

This project is built with AI assistance. See [SPEC.md](SPEC.md) for architecture and design decisions.

## Conventions

- Async Python throughout (3.12+)
- No web frameworks — raw ASGI / uvicorn
- Minimal dependencies: httpx, aiosqlite, uvicorn
- Keep the core small and auditable
