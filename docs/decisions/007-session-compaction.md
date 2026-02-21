# 007: Session history and compaction

**Date:** 2026-02-21
**Status:** Accepted

## Context

Long-running chat sessions exceed context windows. We need durable continuity without heavy machinery.

## Decision

Use bounded live history plus lightweight compaction to memory files.

## Policy

- Keep a rolling recent conversation window in prompt context.
- When history nears configured token limits:
  - summarize older turns into today's `logs/YYYY-MM-DD.md`
  - promote stable user preferences/facts to `MEMORY.md` when appropriate
  - prune summarized turns from active context
- Compaction is deterministic and auditable via local logs.

## Rationale

- Preserves continuity without unbounded context growth.
- Reuses existing file-first memory model.
- Keeps implementation small relative to advanced orchestrators.

## Rejected alternatives

- Infinite raw history injection (unbounded and expensive).
- Complex multi-stage memory pipelines in v1 (too much code for marginal gain).
