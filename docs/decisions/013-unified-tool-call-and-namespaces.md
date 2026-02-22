# 013: Individual built-in tools with `tool_call` catch-all for extensions

**Date:** 2026-02-21
**Status:** Accepted (revised 2026-02-22)

## Context

The runtime supports built-in tools, local extension tools, and MCP tools. The model needs proper schemas and descriptions for built-in tools, while extension and MCP tools are discovered dynamically.

## Decision

Built-in tools (`read`, `write`, `edit`, `bash`, `memory_save`, `memory_search`, `set_profile`) are each registered individually with typed parameters and descriptions. The model sees full schemas for each.

Extension and MCP tools are called through a single `tool_call(name, args)` catch-all. Tool resolution is namespace-based:
- Extension tools: `<tool_name>` (filename-based)
- MCP tools: `MCP__<server>__<tool>`

## Policy

- Built-in tools are registered via `@agent.tool_plain` with typed signatures.
- Extension and MCP tools are listed in the system prompt so the model knows what's available.
- `tool_call` routes by exact `name` lookup in the unified extension/MCP registry.
- MCP registrations are prefixed with `MCP__`.
- Extension tool names starting with `MCP__` are rejected at registration time.
- Name collisions in the registry fail fast with clear startup/reload errors.

## Rationale

- Individual registration gives the model proper schemas and descriptions, improving tool-calling accuracy.
- `tool_call` catch-all keeps the dynamic tool surface simple without requiring re-registration when extensions change.
- Explicit MCP namespace prevents accidental collisions.

## Rejected alternatives

- Single `tool_call` for everything (model gets no schemas for built-in tools, has to guess parameter names).
- Register all tools individually including extensions (requires dynamic agent reconstruction on hot-reload).
