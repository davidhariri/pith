"""Interactive terminal TUI."""

from __future__ import annotations

from .runtime import ChatEvent, Runtime


def _format_event(event: ChatEvent) -> str:
    if event.type == "assistant_delta":
        return event.content
    if event.type == "assistant":
        return event.content
    if event.type == "tool_call":
        return f"\n[tool] {event.content}\n"
    if event.type == "tool_error":
        return f"\n[tool-error] {event.content}\n"
    if event.type == "model_tool_call":
        return f"\n[model] tool call: {event.content}\n"
    if event.type == "model_tool_result":
        return f"[model] tool result: {event.content}\n"
    return f"\n[{event.type}] {event.content}\n"


async def run_chat(runtime: Runtime) -> None:
    session_id = await runtime.storage.ensure_active_session()
    print("pith chat - type /new, /compact, /info, or /quit")

    def _on_event(event: ChatEvent) -> None:
        text = _format_event(event)
        if text:
            print(text, end="", flush=True)

    while True:
        try:
            user_input = input("\npith> ")
        except EOFError:
            break

        if user_input.strip().lower() == "/quit":
            break

        if user_input == "/new":
            session_id = await runtime.new_session()
            print(f"new session: {session_id}")
            continue

        if user_input == "/compact":
            msg = await runtime.compact_session(session_id)
            print(msg)
            continue

        if user_input == "/info":
            info = await runtime.get_info(session_id)
            print(info)
            continue

        def stream_handler(event: ChatEvent) -> None:
            _on_event(event)

        result = await runtime.chat(user_input, session_id=session_id, stream=True, emitter=stream_handler)
        print()
        print(result)
