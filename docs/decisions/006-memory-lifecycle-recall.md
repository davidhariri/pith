# 006: Memory lifecycle and retrieval policy

**Date:** 2026-02-21
**Status:** Accepted

## Context

We want durable memory with minimal moving parts and no dual source of truth.

## Decision

Use DB-native canonical memory in SQLite with FTS5 retrieval and explicit lifecycle rules.

## Canonical stores

- `memory_entries` table for durable memory records.
- `memory_fts` virtual table (FTS5) for full-text retrieval.
- Optional metadata columns: `kind`, `tags`, `source`, `created_at`, `updated_at`.

## Write policy

- `memory_save(...)` inserts memory records directly into SQLite.
- Records may be tagged as `durable` or `episodic`.
- Promotion/cleanup is done by updating DB records, not rewriting markdown files.
- No automatic hard deletion in v1; use soft-delete/tombstone flags where needed.

## Retrieval policy

- Query `memory_fts` directly with FTS ranking plus lightweight recency weighting.
- `memory_search` returns full matched entries with source metadata.
- Inject top-N de-duplicated full entries per turn.

## Rationale

- Single source of truth removes file/index mismatch risk.
- Retrieval stays fast and dependency-light.
- Lifecycle policy remains simple and explicit.

## Rejected alternatives

- File-first canonical memory plus DB index (dual-write complexity).
- Embedding/vector stack in v1 (more complexity than needed now).
