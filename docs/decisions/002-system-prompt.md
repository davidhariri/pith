# 002: Fixed prompt + soul + DB-native memory context

**Date:** 2026-02-21 (updated)
**Status:** Accepted

## Context

The agent must stay stable while still learning over time. We need clear separation between immutable behavior constraints, evolving persona, stable profile records, and durable continuity storage.

## Decision

Four layers:

1. Fixed system prompt in code (not editable by agent at runtime).
2. `SOUL.md` injected every turn (agent-editable persona layer).
3. Runtime-managed profile records in SQLite (agent identity and user identity).
4. DB-native memory and session history in SQLite with indexed recall.

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

### 4. DB-native memory + session history + indexed recall

Memory and session continuity are stored directly in SQLite.

- `memory_save` writes durable memory entries into DB tables.
- `memory_search` queries SQLite FTS5 and returns full matched entries with metadata.
- Session messages are persisted in DB and compacted as needed.
- On each turn, top memory hits are queried and injected.

## Context assembly

1. Fixed system prompt (bootstrap or normal)
2. `SOUL.md`
3. Profile summary (SQLite)
4. Relevant full memory entries from SQLite FTS5 index
5. Conversation history window
6. New message

## Rationale

- Protects core behavior from accidental self-corruption.
- Preserves the "alive" quality through an evolving soul file.
- Keeps identity data stable and less noisy than constantly rewritten files.
- Eliminates dual-write drift between memory files and retrieval index.

## Rejected alternatives

- Agent-editable system prompt (too fragile).
- File-deletion-controlled bootstrap lifecycle (nondeterministic).
- Fully freeform constantly edited identity files (too unstable).
- File-first memory with DB-indexed retrieval (extra complexity and potential drift).
