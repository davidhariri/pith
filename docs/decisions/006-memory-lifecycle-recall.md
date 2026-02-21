# 006: Memory lifecycle and retrieval policy

**Date:** 2026-02-21
**Status:** Accepted

## Context

We want OpenClaw-like memory ergonomics but with a smaller implementation surface.

## Decision

Use file-first canonical memory with FTS5 retrieval and explicit lifecycle rules.

## Canonical stores

- `MEMORY.md`: durable profile, stable preferences, long-lived facts.
- `logs/YYYY-MM-DD.md`: daily episodic notes.

## Write policy

- `memory_save(...)` appends to today's `logs/YYYY-MM-DD.md` by default.
- Durable facts discovered in logs are periodically promoted into `MEMORY.md`.
- No automatic deletion of canonical memory files in v1.

## Retrieval policy

- Index `MEMORY.md` and `logs/*.md` into SQLite FTS5.
- Retrieve with FTS ranking plus lightweight recency weighting by log date.
- `memory_search` returns full matched entries with source metadata.
- Inject top-N de-duplicated full entries per turn.

## Rationale

- Human-readable memory as source of truth.
- Retrieval stays fast and dependency-light.
- Lifecycle policy avoids memory drift while staying simple.

## Rejected alternatives

- DB-only canonical memory (less transparent to humans).
- Embedding/vector stack in v1 (more complexity than needed now).
