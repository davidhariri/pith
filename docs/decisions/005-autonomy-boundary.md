# 005: Two-zone autonomy for self-editing

**Date:** 2026-02-21 (updated)
**Status:** Accepted

## Context

The goal is maximum capability growth through self-editing, without sacrificing reliability or safety.

## Decision

Adopt a two-zone mutability model.

### Zone A: Autonomous writes (default allowed)

The agent may freely create/edit these paths:
- `workspace/extensions/tools/*`
- `workspace/extensions/channels/*`
- `SOUL.md`
- other user workspace scratch files

The agent may write memory through runtime tools (`memory_save`) rather than direct memory file edits.

### Zone B: Guarded core and profile state

Core runtime/spec files and runtime profile records are not auto-mutated by autonomous behavior.

Guarded state includes:
- core runtime/source/spec docs
- `agent_profile` and `user_profile` runtime records
- bootstrap completion state
- external runtime config (`config.yaml` loaded outside workspace)

Profile updates are allowed during bootstrap and otherwise require explicit user direction.

## Rationale

- Enables rapid self-growth where it matters most (extensions + soul + memory).
- Prevents accidental mutation of critical identity and control state.
- Keeps operational model simple and auditable.

## Rejected alternatives

- Fully unrestricted self-edit across all files/records (too fragile).
- Fully locked runtime with no self-editing (too weak for project goals).
