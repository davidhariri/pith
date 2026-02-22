# 004: Docker as optional container runtime

**Date:** 2026-02-21
**Status:** Accepted (revised 2026-02-22)

## Context

The agent process benefits from container isolation for safety, but requiring Docker as a hard dependency adds friction to setup and local development.

## Decision

Docker is available but optional. The primary run path is `uv run pith` locally. A Dockerfile is included for containerized deployment.

Safety without Docker relies on path sandboxing — all file tools resolve paths relative to the workspace and reject escapes. Docker adds process-level isolation on top when used.

## Rationale

- **Low friction.** `uv sync && uv run pith setup` is the entire onboarding. No Docker install, no daemon, no image builds.
- **Path sandboxing is sufficient for local use.** The agent only accesses files within its workspace directory. Escape attempts are rejected at the tool level.
- **Docker for production.** Long-running deployments (e.g. Telegram bot) benefit from container isolation and can use the included Dockerfile.
- **Simplicity.** One CLI (`pith`) handles all commands. No Makefile, no shell scripts for orchestration.

## Rejected alternatives

- **Docker required:** Added significant setup friction (Docker Desktop install, daemon running, image builds) for marginal safety benefit in local/dev use.
- **Docker + Podman:** Multiple container runtimes means multiple codepaths. Not worth the testing burden.
