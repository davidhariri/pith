"""Interactive TUI for pith chat."""

from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from rich.console import Console

from .runtime import Runtime

console = Console()

_PROMPT = ANSI("\033[36mpith>\033[0m ")


async def _send(runtime: Runtime, message: str, session_id: str) -> None:
    """Send a message and stream the response to stdout."""

    def on_text(delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()

    def on_tool(name: str) -> None:
        console.print(f"[yellow]\\[tool][/yellow] {name}")

    await runtime.chat(
        message,
        session_id=session_id,
        on_text=on_text,
        on_tool=on_tool,
    )
    print()


async def run_chat(runtime: Runtime) -> None:
    session_id = await runtime.storage.ensure_active_session()
    history_path = runtime.workspace / ".pith" / "input_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
    )

    bootstrap_complete = await runtime.storage.get_bootstrap_state()

    if not bootstrap_complete:
        # First run — kick off bootstrap to collect identities
        console.print("[bold]welcome to pith[/bold]  (type /quit to exit)\n")
        await _send(runtime, "Hello — let's get started.", session_id)
    else:
        # Resuming — show session context
        history = await runtime.storage.get_message_history(session_id)
        profiles = await runtime.storage.all_profile_fields()
        agent_name = profiles.get("agent", {}).get("name", "pith")
        if history:
            console.print(f"[bold]{agent_name}[/bold]  resuming session  (type /quit to exit)")
        else:
            console.print(f"[bold]{agent_name}[/bold]  new session  (type /quit to exit)")

    while True:
        try:
            user_input = await session.prompt_async(_PROMPT)
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
