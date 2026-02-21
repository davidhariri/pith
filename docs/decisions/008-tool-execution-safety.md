# 008: Tool execution and safety boundary

**Date:** 2026-02-21
**Status:** Accepted

## Context

The project goal is broad in-container freedom for the agent, with safety derived from containment and minimal policy overhead.

## Decision

Container boundary is the primary safety mechanism. In-container tool execution is permissive by default.

## Policy

- `bash` and extension tools may run freely inside the container.
- Host impact is limited by container isolation and workspace mount boundaries.
- No Docker socket mount.
- Core runtime applies pragmatic safeguards:
  - per-tool timeout
  - retries/backoff for transient failures
  - structured error propagation to model loop

## Extension load safety

- Extension loader validates required function contracts.
- On load/import failure, extension is marked unavailable and error is logged.
- Runtime stays alive even when individual extensions fail.

## Rationale

- Maximizes experimentation and capability growth.
- Avoids building a large in-app permission system.
- Keeps the implementation compact while preserving real isolation.

## Rejected alternatives

- Fine-grained in-process ACL engine in v1 (too heavy).
- Uncontained host execution (violates core safety goal).
