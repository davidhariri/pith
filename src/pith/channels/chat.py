"""Interactive TUI for pith chat."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console

from ..client import PithClient

console = Console()

_style = Style.from_dict(
    {
        "placeholder": "gray italic",
        "completion-menu": "bg:default default",
        "completion-menu.completion.current": "bold",
    }
)

_slash_completer = WordCompleter(
    ["/quit", "/new", "/compact", "/info"],
    sentence=True,
)

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


async def _send(client: PithClient, message: str, session_id: str) -> bool:
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

    def on_tool_call(name: str, args: dict) -> None:
        nonlocal started, spinner_task
        if not started:
            started = True
            if spinner_task:
                spinner_task.cancel()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        # Format args inline, truncating long values
        parts = []
        for k, v in args.items():
            s = str(v)
            if len(s) > 40:
                s = s[:37] + "..."
            parts.append(f'{k}="{s}"' if isinstance(v, str) else f"{k}={s}")
        arg_str = " ".join(parts)
        console.print(f"  [dim]{name} {arg_str}[/dim]")

    def on_tool_result(name: str, success: bool) -> None:
        nonlocal started, spinner_task
        if not success:
            if not started:
                started = True
                if spinner_task:
                    spinner_task.cancel()
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            console.print(f"  [red]✗ {name}[/red]")

    async def on_secret_request(name: str) -> str:
        nonlocal started, spinner_task
        if not started:
            started = True
            if spinner_task:
                spinner_task.cancel()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        console.print()
        console.print(f"  [yellow bold]secret needed:[/yellow bold] {name}")
        pw_session: PromptSession[str] = PromptSession()
        value = await pw_session.prompt_async(
            "  paste value (hidden): ",
            is_password=True,
        )
        console.print("  [green]saved[/green]")
        console.print()
        return value

    try:
        spinner_task = asyncio.create_task(_spin())
        await client.chat(
            message,
            session_id=session_id,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_secret_request=on_secret_request,
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


async def _greet(client: PithClient, session_id: str) -> None:
    """Send an opening signal so the LLM greets the user."""
    info = await client.get_info(session_id)
    bootstrap = not info.get("bootstrap_complete", True)
    console.print()
    if bootstrap:
        await _send(client, "Hello — I just started pith for the first time.", session_id)
    else:
        await _send(
            client,
            "[new conversation — greet the user briefly, don't re-introduce yourself]",
            session_id,
        )


async def run_chat(client: PithClient) -> None:
    session_id = await client.new_session()

    history_dir = Path.home() / ".local" / "share" / "pith"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / "input_history"

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        placeholder=[("class:placeholder", "say something...")],
        completer=_slash_completer,
        complete_while_typing=True,
    )

    await _greet(client, session_id)

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
            session_id = await client.new_session()
            await _greet(client, session_id)
            continue
        if text == "/compact":
            result = await client.compact_session(session_id)
            console.print(result)
            continue
        if text == "/info":
            info = await client.get_info(session_id)
            bootstrap = info.get("bootstrap_complete", False)
            agent = info.get("agent_profile", {})
            user = info.get("user_profile", {})
            console.print(f"  session    {info.get('session_id', '?')}")
            console.print(f"  messages   {info.get('message_count', 0)}")
            status = "[green]complete[/green]" if bootstrap else "[yellow]pending[/yellow]"
            console.print(f"  bootstrap  {status}")
            if agent:
                console.print(f"  agent      {', '.join(f'{k}={v}' for k, v in agent.items())}")
            if user:
                console.print(f"  user       {', '.join(f'{k}={v}' for k, v in user.items())}")
            continue

        await _send(client, text, session_id)
