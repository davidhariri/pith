# 008: Tool execution and safety boundary

**Date:** 2026-02-21
**Status:** Accepted (revised 2026-02-22)

## Context

The agent needs to read/write files and execute code, but must not have unrestricted host access.

## Decision

Tool-level sandboxing is the primary safety mechanism. No shell access. Code execution uses Monty.

## Policy

- **No bash/shell tool.** The agent cannot run arbitrary commands on the host.
- **File tools** (`read`, `write`, `edit`) enforce workspace path sandboxing — all paths resolve relative to the workspace root and escape attempts are rejected.
- **`run_python`** executes code through Monty (Pydantic's Rust-based Python subset interpreter). Monty has no filesystem, network, or import access. The only bridge to the host is three explicitly provided functions (`read`, `write`, `edit`) that go through the same workspace-sandboxed implementations.
- Extension and MCP tools are routed through `tool_call` with structured error propagation.
- Per-tool output size limits prevent runaway responses.

## Extension load safety

- Extension loader validates required function contracts.
- On load/import failure, extension is marked unavailable and error is logged.
- Runtime stays alive even when individual extensions fail.

## Rationale

- Eliminates the largest attack surface (arbitrary shell execution) without losing meaningful capability.
- Monty provides safe computation (microsecond startup, no side effects beyond provided functions).
- File sandboxing is simple, auditable, and doesn't require container infrastructure.
- Keeps the implementation compact while preserving real isolation.

## Rejected alternatives

- **Container boundary as primary safety:** Required Docker as a hard dependency, added lifecycle complexity, and still needed tool-level sandboxing inside the container anyway.
- **Fine-grained in-process ACL engine:** Too heavy for v1.
- **Unrestricted `bash` tool with path-only sandboxing:** Shell commands can trivially escape path restrictions via network access, process spawning, environment variable reading, etc.
