# 011: Bootstrap state machine and profile ownership

**Date:** 2026-02-21
**Status:** Accepted

## Context

We want the first-run "coming alive" experience without relying on fragile agent-side file choreography.

## Decision

Bootstrap lifecycle is runtime-controlled and persisted in SQLite.

## State model

Runtime stores bootstrap and profile state in SQLite:

- `app_state.bootstrap_complete` (boolean)
- `app_state.bootstrap_version` (integer)
- `agent_profile` (name, nature, vibe, emoji, optional notes)
- `user_profile` (name, preferred address, timezone, notes)

## Prompt mode selection

- If required profile fields are missing or `bootstrap_complete = false`, runtime uses bootstrap prompt mode.
- Once required fields are present, runtime sets `bootstrap_complete = true` and switches to normal prompt mode.

Bootstrap completion is based on runtime validation, not model self-declaration.

## Ownership model

- `SOUL.md` is always injected and agent-editable.
- `agent_profile` and `user_profile` are guarded runtime records.
- Post-bootstrap profile changes require explicit user direction.

## Optional file mirrors

`IDENTITY.md` and `USER.md` may exist as export snapshots for human readability, but they are not control-plane state and not required for prompt-mode transitions.

## Rationale

- Deterministic startup behavior.
- Clear separation between evolving personality (`SOUL.md`) and stable identity records.
- Less drift and less prompt noise over long-running sessions.

## Rejected alternatives

- Relying on deleting `BOOTSTRAP.md` to exit bootstrap mode.
- Treating identity files as continuously self-mutating freeform memory.
