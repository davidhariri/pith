# 003: File-system-based extension interface

**Date:** 2026-02-21
**Status:** Accepted

## Context

Extensions are Python modules the agent writes at runtime and the system hot-reloads. We need a convention for how extensions declare their tools and channels.

## Decision

The file system is the registry. Two extension types: tools and channels. No hooks — the agent handles its own reasoning.

### Directory structure

```
workspace/extensions/
├── tools/
│   ├── get_weather.py
│   └── send_email.py
└── channels/
    └── slack.py
```

### Tools

Each file in `extensions/tools/` is one tool. It must define `async def run(...)`:

```python
# extensions/tools/get_weather.py

async def run(city: str) -> str:
    """Get current weather for a city."""
    return await _fetch(f"https://wttr.in/{city}?format=3")

async def _fetch(url: str) -> str:
    async with httpx.AsyncClient() as client:
        return (await client.get(url)).text
```

- **Tool name** = filename (`get_weather`)
- **Description** = docstring of `run`
- **Parameter schema** = type hints of `run`
- **Helpers** = underscore-prefixed, ignored by loader

### Channels

Each file in `extensions/channels/` is a messaging platform adapter. It must define three functions:

```python
# extensions/channels/slack.py

async def connect() -> None:
    """Initialize Slack connection and authenticate."""
    ...

async def recv() -> Message:
    """Wait for and return the next incoming message."""
    ...

async def send(message: Message) -> None:
    """Send a response back to Slack."""
    ...
```

- **Channel name** = filename (`slack`)
- **Description** = module docstring or `connect`'s docstring
- **Contract** = `connect()`, `recv()`, `send()` — the loader checks all three exist

The core Telegram channel implements the same three-function contract, just in the core codebase where the agent can't break it. Agent-written channels in `extensions/channels/` are hot-reloaded and can be added/modified at runtime.

`Message` is a simple dataclass from pith's core — the one shared type:

```python
@dataclass
class Message:
    text: str
    sender: str
    channel: str
    metadata: dict | None = None
```

### Loader behavior

- Watch `workspace/extensions/` for changes
- On change, reimport the module
- For tools: grab `run`, error if missing
- For channels: grab `connect`, `recv`, `send`, error if any are missing
- Hot-reload: reimport module, re-register

## Rationale

- **Zero coupling to pith.** Extensions are plain Python files. No decorators, no registration. The agent writes functions and drops them in a folder. (Channels import `Message` for type hints but that's optional.)
- **File system is the registry.** No manifest, no config. `ls extensions/tools/` tells you what tools exist. `ls extensions/channels/` tells you what channels exist.
- **Agent-friendly.** An LLM writes a file with known function signatures — the simplest possible contract.
- **Hot-reload is trivial.** Reimport the module, re-grab the functions.
- **Channels are safe by default.** Telegram is core infrastructure. Agent-written channels extend reach without risking the primary communication path.
- **No hooks.** The agent handles its own pre/post processing through reasoning. One less concept to learn and maintain.

## Rejected alternatives

- **Decorators (`@tool`, `@hook`):** Requires importing from pith. Creates coupling between extensions and the framework.
- **Base class for channels:** Heavier than needed. Three known functions is a structural interface without the inheritance baggage.
- **Hooks directory:** Unnecessary abstraction. The agent can handle pre/post processing in its own reasoning loop.
- **Single directory for everything:** Tools and channels have fundamentally different shapes (one-shot vs long-running). Pretending they're the same would be forced.
- **inbox/outbox queues for channels:** More flexible but harder for the agent to write correctly. Three named functions are a clearer contract.
