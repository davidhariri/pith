"""Interactive TUI for pith chat."""

from __future__ import annotations

import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console

from ..runtime import Runtime

console = Console()

_style = Style.from_dict({
    "placeholder": "gray italic",
    "completion-menu": "bg:default default",
    "completion-menu.completion.current": "bold",
})

_slash_completer = WordCompleter(
    ["/quit", "/new", "/compact", "/info"],
    sentence=True,
)

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


async def _send(runtime: Runtime, message: str, session_id: str) -> bool:
    """Send a message and stream the response to stdout. Returns True on success."""
    started = False
    spinner_task: asyncio.Task[None] | None = None

    async def _spin() -> None:
        """Show a thinking spinner until the first token arrives."""
        i = 0
        while True:
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            sys.stdout.write(f"\r\033[2m{frame}\033[0m")
            sys.stdout.flush()
            i += 1
            await asyncio.sleep(0.08)

    def on_text(delta: str) -> None:
        nonlocal started, spinner_task
        if not started:
            started = True
            if spinner_task:
                spinner_task.cancel()
            # Clear the spinner line
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        sys.stdout.write(delta)
        sys.stdout.flush()

    def on_tool(name: str) -> None:
        nonlocal started, spinner_task
        if not started:
            started = True
            if spinner_task:
                spinner_task.cancel()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        console.print(f"[yellow]\\[tool][/yellow] {name}")

    try:
        spinner_task = asyncio.create_task(_spin())
        await runtime.chat(
            message,
            session_id=session_id,
            on_text=on_text,
            on_tool=on_tool,
        )
        if spinner_task and not spinner_task.done():
            spinner_task.cancel()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        print()
        return True
    except Exception as exc:
        if spinner_task and not spinner_task.done():
            spinner_task.cancel()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        msg = str(exc)
        if "401" in msg or "AuthenticationError" in type(exc).__name__:
            console.print("\n[red]error:[/red] invalid API key — run `pith setup` to reconfigure")
            raise SystemExit(1) from None
        console.print(f"\n[red]error:[/red] {type(exc).__name__}: {msg}")
        return False


async def _greet(runtime: Runtime, session_id: str) -> None:
    """Send an opening signal so the LLM greets the user."""
    bootstrap = not await runtime.storage.get_bootstrap_state()
    console.print()
    if bootstrap:
        await _send(runtime, "Hello — I just started pith for the first time.", session_id)
    else:
        await _send(runtime, "[new conversation]", session_id)


async def run_chat(runtime: Runtime) -> None:
    session_id = await runtime.new_session()
    history_path = runtime.workspace / ".pith" / "input_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        placeholder=[("class:placeholder", "say something...")],
        completer=_slash_completer,
        complete_while_typing=True,
    )

    await _greet(runtime, session_id)

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
            await _greet(runtime, session_id)
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
