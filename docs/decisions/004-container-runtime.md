# 004: Docker as optional deployment runtime

**Date:** 2026-02-21
**Status:** Accepted (revised 2026-02-22)

## Context

The agent process benefits from isolation for safety, but requiring Docker as a hard dependency adds friction to setup and local development.

## Decision

Docker is available but optional — for deployment only, not for sandboxing. The primary run path is `uv run pith` locally. A Dockerfile is included for containerized deployment.

Safety comes from tool-level sandboxing:
- File tools (`read`/`write`/`edit`) resolve paths relative to the workspace and reject escapes.
- Code execution uses Monty (Pydantic's Rust-based Python subset interpreter) — no filesystem, network, or import access except through explicitly provided host functions.
- No shell/bash tool. The agent cannot run arbitrary commands.

## Rationale

- **Low friction.** `uv sync && uv run pith setup` is the entire onboarding. No Docker install, no daemon, no image builds.
- **Tool-level sandboxing is sufficient.** The agent only accesses files within its workspace directory via sandboxed tools. Code execution is confined to Monty's restricted interpreter.
- **Docker for production.** Long-running deployments (e.g. Telegram bot) benefit from container isolation and can use the included Dockerfile.
- **Simplicity.** One CLI (`pith`) handles all commands. No Makefile, no shell scripts for orchestration.

## Rejected alternatives

- **Docker required for sandboxing:** Added significant setup friction (Docker Desktop install, daemon running, image builds) and container lifecycle complexity for marginal safety benefit when tool-level sandboxing already prevents escape.
- **Docker + Podman:** Multiple container runtimes means multiple codepaths. Not worth the testing burden.
