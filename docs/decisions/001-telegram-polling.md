# 001: Long-polling as default Telegram transport

**Date:** 2026-02-21
**Status:** Accepted

## Context

Telegram Bot API supports two modes for receiving updates: long-polling (`getUpdates`) and webhooks. We need to choose a default for pith's Telegram channel.

## Decision

Long-polling is the default. Webhook is an optional configuration for users with a public HTTPS endpoint.

## Rationale

- **No infrastructure requirements.** Long-polling needs no public URL, TLS cert, or domain. It just works on any machine with outbound internet.
- **Simpler implementation.** One async loop calling `getUpdates` with a timeout. No HTTP server needed for the Telegram channel itself.
- **Fits the use case.** Pith is a single-user personal agent. The latency difference between polling (~1-2s) and webhooks (~instant) is negligible for chat.
- **Precedent.** OpenClaw uses the same approach — long-polling default, webhook opt-in.

## Implementation

- Hit the Telegram Bot API directly with `httpx` (no bot framework)
- `getUpdates` with 30s long-poll timeout
- Persist last `update_id` to disk for clean resume after restart
- Exponential backoff on transient failures
- Optional webhook mode later if needed (uvicorn already in the stack)

## Rejected alternatives

- **Webhook-only:** Requires a public URL, which most local/self-hosted setups don't have. Adds setup friction for no real benefit at this scale.
- **Bot framework (python-telegram-bot, aiogram):** Unnecessary abstraction. The Bot API is simple enough to call directly with httpx, and we avoid a dependency that would obscure what's happening.
