# 002: System prompt architecture

**Date:** 2026-02-21
**Status:** Accepted

## Context

The agent needs a system prompt, but we need to decide what's fixed vs. evolving, and how memory/context gets injected. Other projects handle this differently:

- **Pi:** Hardcoded minimal prompt, context stored in session state.
- **NanoClaw:** Delegates to Claude Code's CLAUDE.md files — agent can edit them freely.
- **OpenClaw:** 700-line runtime-assembled prompt with workspace .md files injected as context blocks.

Letting the agent edit its own system prompt is risky — one bad edit and it forgets its tools or overwrites constraints.

## Decision

Three-layer separation: fixed prompt in code, memories in SQLite searched on the fly, workspace files on disk readable on demand.

### 1. Fixed system prompt (in code, agent cannot edit)

The core prompt lives in Python source. It defines:
- Agent identity and behavioral rules
- Available built-in tools and their descriptions
- Instructions for using memory and workspace
- Safety constraints

This never changes at runtime. The agent can't accidentally break itself.

### 2. Memories (in SQLite, searched per-turn)

Stored in the SQLite database via FTS5. On each incoming message, the system automatically queries for relevant memories and injects the top-N results into the context window. The agent can also explicitly manage memories via tools:

- `memory_save(content, tags)` — store a new memory
- `memory_search(query, limit)` — search memories by keyword

This keeps memory scalable — thousands of entries without bloating the prompt. Only relevant memories appear in context.

### 3. Workspace files (on disk, agent-readable/writable)

The agent's mounted workspace directory can contain any files the agent creates — notes, plans, research, config. These are **not** auto-injected into the prompt. The agent uses its `read` tool to access them when needed.

This gives the agent a persistent scratchpad without the risk of injecting unbounded content into every turn.

### Context assembly per turn

```
┌─────────────────────────────────┐
│ Fixed system prompt (from code) │
├─────────────────────────────────┤
│ Relevant memories (FTS5 query)  │
├─────────────────────────────────┤
│ Conversation history            │
├─────────────────────────────────┤
│ New message                     │
└─────────────────────────────────┘
```

## Rationale

- **Fixed prompt prevents self-sabotage.** The agent can't forget its tools or overwrite safety rules.
- **DB-backed memory scales.** FTS5 search means we can store thousands of memories and only surface what's relevant. No context window bloat.
- **Workspace files stay out of the way.** Available when the agent wants them, invisible when it doesn't. No accidental prompt injection from large files.
- **Simple to implement.** No file-watching for prompt changes, no assembly function, no workspace file scanning. Just a string constant + a DB query + conversation history.

## Rejected alternatives

- **Agent-editable system prompt (NanoClaw style):** Risk of the agent breaking its own instructions. No guardrail against catastrophic edits.
- **Structured workspace files injected into prompt (OpenClaw style):** Complexity of scanning, ordering, and truncating multiple files. Prompt size becomes unpredictable.
- **No memory system, just conversation history:** Doesn't scale. Long-running agents need persistent knowledge beyond the context window.
