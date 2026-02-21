# 010: Provider-agnostic model adapter

**Date:** 2026-02-21
**Status:** Accepted

## Context

We want model portability without a large abstraction layer.

## Decision

Define one internal model interface and one canonical tool-calling shape. Implement adapters per provider only when needed.

## Policy

- Core loop talks to a provider-agnostic internal interface.
- Start with an OpenAI-compatible adapter path.
- Keep adapter responsibilities narrow:
  - request/response translation
  - tool call translation
  - retryable error mapping

## Rationale

- Reduces lock-in.
- Keeps code small and understandable.
- Avoids over-design before multiple providers are actually required.

## Rejected alternatives

- Single hardcoded provider forever (too rigid).
- Large universal SDK abstraction in v1 (too much code).
