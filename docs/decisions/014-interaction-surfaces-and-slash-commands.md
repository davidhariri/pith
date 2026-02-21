# 014: Primary CLI TUI, limited Telegram, shared slash commands

**Date:** 2026-02-21
**Status:** Accepted

## Context

Pith needs two operator surfaces:
- A high-signal local interface for building and debugging (`pith chat`)
- A lightweight remote interface (Telegram)

The local interface should expose runtime visibility (streaming and tool activity), while Telegram should stay simpler and lower-noise.

## Decision

- `pith chat` is a first-class interactive TUI with streaming assistant output.
- `pith chat` renders runtime execution states and tool-call events during each turn.
- Telegram remains intentionally limited: concise text-focused interaction without full live event streaming.
- Both CLI chat and Telegram support the same core slash commands:
  - `/new` start a new session
  - `/compact` compact current session history
  - `/info` show runtime/session info
- Slash commands are handled by runtime command routing before model invocation.

## Rationale

- Keeps developer/operator workflow fast and inspectable in the terminal.
- Preserves a simple mobile/remote control channel through Telegram.
- Shared slash command semantics reduce cognitive overhead across channels.

## Rejected alternatives

- Equal-feature Telegram and CLI UX (too noisy and brittle in chat UX).
- CLI without streaming/runtime event visibility (poor debugging and operator confidence).
- Channel-specific command sets for basic session operations (inconsistent mental model).
