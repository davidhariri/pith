# 009: Minimal local observability

**Date:** 2026-02-21
**Status:** Accepted

## Context

A self-editing agent needs enough visibility for debugging and trust, without introducing heavy telemetry systems.

## Decision

Use local, append-only structured logs as the default observability surface.

## Policy

Record JSONL events for:
- turns (input/output metadata)
- tool calls (name, args summary, outcome, duration)
- memory retrieval (query + returned source metadata)
- extension reload results and failures

Keep logs local to workspace runtime paths. No external telemetry required.

## Rationale

- Easy to inspect with standard tools.
- Supports audits and debugging of autonomous behavior.
- Minimal code footprint.

## Rejected alternatives

- Full tracing stack in v1 (overkill).
- No structured logs (too opaque for a self-modifying agent).
