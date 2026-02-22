"""Interactive TUI for pith chat."""

from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from .runtime import Runtime


async def run_chat(runtime: Runtime) -> None:
    session_id = await runtime.storage.ensure_active_session()
    history_path = runtime.workspace / ".pith" / "input_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
    )

    print("pith chat (type /quit to exit)")

    while True:
        try:
            user_input = await session.prompt_async("\033[36mpith>\033[0m ")
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
            print(f"new session: {session_id}")
            continue
        if text == "/compact":
            result = await runtime.compact_session(session_id)
            print(result)
            continue
        if text == "/info":
            info = await runtime.get_info(session_id)
            print(info)
            continue

        def on_text(delta: str) -> None:
            sys.stdout.write(delta)
            sys.stdout.flush()

        def on_tool(name: str) -> None:
            print(f"\033[33m[tool] {name}\033[0m")

        await runtime.chat(
            text,
            session_id=session_id,
            on_text=on_text,
            on_tool=on_tool,
        )
        # Newline after streamed output
        print()
