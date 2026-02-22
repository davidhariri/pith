"""Interactive TUI for pith chat."""

from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console

from ..runtime import Runtime

console = Console()

_style = Style.from_dict({
    "placeholder": "gray italic",
})


async def _send(runtime: Runtime, message: str, session_id: str) -> bool:
    """Send a message and stream the response to stdout. Returns True on success."""

    def on_text(delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()

    def on_tool(name: str) -> None:
        console.print(f"[yellow]\\[tool][/yellow] {name}")

    try:
        await runtime.chat(
            message,
            session_id=session_id,
            on_text=on_text,
            on_tool=on_tool,
        )
        print()
        return True
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "AuthenticationError" in type(exc).__name__:
            console.print("\n[red]error:[/red] invalid API key — run `pith setup` to reconfigure")
            raise SystemExit(1) from None
        console.print(f"\n[red]error:[/red] {type(exc).__name__}: {msg}")
        return False


async def run_chat(runtime: Runtime) -> None:
    session_id = await runtime.storage.ensure_active_session()
    history_path = runtime.workspace / ".pith" / "input_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        placeholder=[("class:placeholder", "say something...")],
    )

    bootstrap_complete = await runtime.storage.get_bootstrap_state()

    if not bootstrap_complete:
        # First run — kick off bootstrap to collect identities
        console.print()
        await _send(runtime, "Hello — let's get started.", session_id)
    else:
        # Resuming — show session context
        history = await runtime.storage.get_message_history(session_id)
        profiles = await runtime.storage.all_profile_fields()
        agent_name = profiles.get("agent", {}).get("name", "pith")
        if history:
            console.print(f"[dim]resuming session with {agent_name}  (/quit to exit)[/dim]")
        else:
            console.print(f"[dim]new session with {agent_name}  (/quit to exit)[/dim]")

    while True:
        try:
            user_input = await session.prompt_async(
                "> ",
                style=_style,
            )
        except (EOFError, KeyboardInterrupt):
            break

        text = user_input.strip()
        if not text:
            continue

        # Slash commands
        if text == "/quit":
            break
        if text == "/new":
            session_id = await runtime.new_session()
            console.print(f"new session: {session_id}")
            continue
        if text == "/compact":
            result = await runtime.compact_session(session_id)
            console.print(result)
            continue
        if text == "/info":
            info = await runtime.get_info(session_id)
            console.print(info)
            continue

        await _send(runtime, text, session_id)
