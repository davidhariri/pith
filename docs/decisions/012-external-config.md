# 012: External runtime config via `config.yaml`

**Date:** 2026-02-21
**Status:** Accepted

## Context

The agent should freely evolve workspace artifacts (extensions, memory, soul) while runtime integrations such as MCP server definitions and model setup remain operator-controlled.

## Decision

Use an external `config.yaml` as runtime control-plane config.

## Policy

- Runtime reads config from `PITH_CONFIG` or default host path `~/.config/pith/config.yaml`.
- In Docker, mount this config file read-only into the container (for example `/run/pith/config.yaml`).
- This config is outside workspace and not part of autonomous agent-writable state.
- MCP server definitions (stdio/http) are configured here.
- MCP tool namespace prefix is configured here (default `MCP__`).
- Model/provider selection and runtime model options are configured here.
- Secrets should be referenced via env vars, not hardcoded in workspace files.
- `.env` (or host environment) supplies API keys/secrets referenced by config.
- For simplicity in v1, config changes are applied on restart.

## Rationale

- Clean separation between operator-owned integration config and agent-owned workspace state.
- Keeps MCP/server/model wiring explicit and auditable.
- Preserves autonomy where it is useful without letting the agent mutate control-plane wiring.

## Rejected alternatives

- In-workspace runtime config (too easy for autonomous drift).
- Env-only config with no file schema (harder to audit and share).
- DB-stored runtime config (heavier than needed in v1).
