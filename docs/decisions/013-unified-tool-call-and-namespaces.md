# 013: Unified `tool_call` and tool namespaces

**Date:** 2026-02-21
**Status:** Accepted

## Context

The runtime supports local extension tools and MCP tools. Calling them through different tool APIs adds complexity and routing ambiguity.

## Decision

Expose one invocation tool: `tool_call(name, args)`.

Tool resolution is namespace-based:
- Extension tools: `<tool_name>` (filename-based)
- MCP tools: `MCP__<server>__<tool>`

## Policy

- Runtime constructs a single tool registry from extension tools and MCP tool descriptors.
- MCP registrations are prefixed with `MCP__`.
- Extension tool names starting with `MCP__` are rejected at registration time.
- Name collisions in the unified registry fail fast with clear startup/reload errors.
- `tool_call` routes by exact `name` lookup in the unified registry.

## Rationale

- One call surface keeps the model-facing contract simple.
- Explicit MCP namespace prevents accidental collisions.
- Fail-fast validation avoids ambiguous behavior at runtime.

## Rejected alternatives

- Separate `mcp_call` plus local tool calls (split surface, extra complexity).
- Unprefixed MCP names (collision-prone).
