# 010: `pydantic-ai` model runtime with `FastAPI`

**Date:** 2026-02-21
**Status:** Accepted

## Context

We want strong model portability and tool-calling support without building and maintaining custom provider adapters.

## Decision

Use `pydantic-ai` as the model/tool compatibility layer and `FastAPI` as the runtime service framework.

## Policy

- Core orchestration uses `pydantic-ai` agents and tools.
- Model/provider selection is configured in external `config.yaml`.
- API keys and secrets are provided via `.env`/environment variables.
- `FastAPI` hosts runtime HTTP endpoints (health, optional webhook/admin surfaces) behind `uvicorn`.
- Avoid writing custom provider adapters unless `pydantic-ai` cannot support a required capability.

## Rationale

- Leverages mature provider compatibility and tool abstractions.
- Shrinks custom core code and maintenance burden.
- Keeps configuration explicit and operator-controlled.

## Rejected alternatives

- Custom in-house model adapter layer (extra code and long-term maintenance).
- Single hardcoded provider forever (too rigid).
