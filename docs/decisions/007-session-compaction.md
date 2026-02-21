# 007: Session history and compaction

**Date:** 2026-02-21
**Status:** Accepted

## Context

Long-running chat sessions exceed context windows. We need durable continuity without heavy machinery.

## Decision

Use bounded live history plus lightweight compaction in SQLite.

## Policy

- Keep a rolling recent conversation window in prompt context.
- When history nears configured token limits:
  - summarize older turns into `session_summaries` records
  - promote stable user preferences/facts into `memory_entries` when appropriate
  - prune summarized turns from active context
- Compaction is deterministic and auditable via local logs.

## Rationale

- Preserves continuity without unbounded context growth.
- Reuses the same SQLite continuity store used by memory.
- Keeps implementation small relative to advanced orchestrators.

## Rejected alternatives

- Infinite raw history injection (unbounded and expensive).
- Complex multi-stage memory pipelines in v1 (too much code for marginal gain).
