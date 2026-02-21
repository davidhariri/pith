# Agents

This project is built with AI assistance. See [SPEC.md](SPEC.md) for architecture and design decisions.

## Conventions

- Async Python throughout (3.12+)
- No web frameworks — raw ASGI / uvicorn
- Use `uv` for environment + dependency management
- Use `ruff` for linting + formatting
- Core runtime deps: pydantic-ai, aiosqlite, uvicorn
- Keep the core small and auditable

## Engineering Principles

- KISS first: choose the simplest design that meets the requirement.
- YAGNI by default: do not build speculative features or abstractions.
- DRY aggressively: one source of truth for each behavior and schema.
- No parallel implementations for the same responsibility.
- Prefer composition over inheritance and indirection-heavy patterns.
- Keep modules small and cohesive, with clear boundaries and names.
- Favor explicit code over framework magic or hidden control flow.
- Add abstractions only after duplication is proven and stable.
- Minimize dependencies; prefer stdlib unless a library clearly reduces complexity.
- Make failures loud and actionable: fast failure, clear errors, no silent fallbacks.
- Optimize for readability and maintainability over cleverness.
- Refactor before extending when code feels duplicated or disorganized.
- Ship in small, verifiable increments; keep diffs focused.
