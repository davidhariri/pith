# 002: Fixed prompt + soul + file-first memory context

**Date:** 2026-02-21 (updated)
**Status:** Accepted

## Context

The agent must stay stable while still learning over time. We need clear separation between immutable behavior constraints, evolving persona, stable profile records, and durable memory.

## Decision

Four layers:

1. Fixed system prompt in code (not editable by agent at runtime).
2. `SOUL.md` injected every turn (agent-editable persona layer).
3. Runtime-managed profile records in SQLite (agent identity and user identity).
4. File-first memory (`MEMORY.md` + `logs/*.md`) with indexed recall.

## Details

### 1. Fixed system prompt

Defines:
- behavioral and safety constraints
- built-in tool contracts
- memory and profile usage rules

This prompt is code-owned and runtime-immutable.

### 2. `SOUL.md`

- `SOUL.md` is always loaded into prompt context.
- The agent may evolve it over time.
- This is the explicit, human-visible personality layer.

### 3. Profile records (SQLite)

Agent identity and user identity are stored as structured runtime records.

- Bootstrap mode can initialize these records.
- After bootstrap, updates are guarded and occur only on explicit user direction.
- These records are injected as compact profile context, not as freeform constantly-mutating text files.

### 4. File-first memory + indexed recall

Canonical memory files:
- `MEMORY.md` for durable, high-signal facts
- `logs/YYYY-MM-DD.md` for daily episodic notes

Runtime indexes memory files into SQLite FTS5.

- On each turn, top memory hits are queried and injected.
- Memory hits include source metadata for traceability.

## Context assembly

1. Fixed system prompt (bootstrap or normal)
2. `SOUL.md`
3. Profile summary (SQLite)
4. Relevant memory chunks from index
5. Conversation history window
6. New message

## Rationale

- Protects core behavior from accidental self-corruption.
- Preserves the "alive" quality through an evolving soul file.
- Keeps identity data stable and less noisy than constantly rewritten files.
- Maintains transparent, durable, human-editable memory.

## Rejected alternatives

- Agent-editable system prompt (too fragile).
- File-deletion-controlled bootstrap lifecycle (nondeterministic).
- Fully freeform constantly edited identity files (too unstable).
