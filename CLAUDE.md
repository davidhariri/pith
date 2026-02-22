# CLAUDE.md

See [SPEC.md](SPEC.md) for architecture. See `docs/decisions/` for design rationale.

## Philosophy

Favor simplicity, explicitness, and small modules. No speculative abstractions. Make failures loud and actionable.

Before adding anything — a function, a module, a dependency — read the full codebase and ask: can something that already exists be slightly adapted instead? New things must fight to exist. The bar is not "is this useful" but "is this worth the complexity it adds." Simpler, more elegant systems become more beloved and easier to use. Spend tokens reading and understanding before writing.

## Tooling

- Async Python 3.12+, no web frameworks
- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `pytest` + `pytest-asyncio` for tests
- `rich` for all terminal output (never raw ANSI escape codes)
- `questionary` for interactive prompts/selectors (never hand-rolled termios)
- `prompt-toolkit` for async chat input with history

## Constraints

- **No new dependencies without justification.** Adding a dep is a decision, not a default. If stdlib or an existing dep can do the job, use it.
- **Container-first safety.** The Docker container is the primary sandbox. Don't add application-level security theater beyond basic path sandboxing.
- **Tests required.** New functionality comes with tests. Changed behavior gets updated tests.
- **Keep the core small and auditable.** A human should be able to read the entire codebase quickly.
