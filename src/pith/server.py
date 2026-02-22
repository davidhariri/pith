"""HTTP API server — Starlette + SSE bridge to Runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .runtime import Runtime


class _SSEResponse(Response):
    """Server-Sent Events response that consumes an async queue."""

    media_type = "text/event-stream"

    def __init__(self, generator: AsyncGenerator[str, None]) -> None:
        super().__init__(content=None)
        self._generator = generator

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"text/event-stream"],
                    [b"cache-control", b"no-cache"],
                    [b"connection", b"keep-alive"],
                ],
            }
        )
        try:
            async for chunk in self._generator:
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk.encode(),
                        "more_body": True,
                    }
                )
        finally:
            await send({"type": "http.response.body", "body": b"", "more_body": False})


def _sse_line(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def create_app(runtime: Runtime) -> Starlette:
    """Build a Starlette app wired to the given Runtime."""

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def session_new(request: Request) -> JSONResponse:
        session_id = await runtime.new_session()
        return JSONResponse({"session_id": session_id})

    async def session_compact(request: Request) -> JSONResponse:
        body = await request.json()
        session_id = body.get("session_id")
        result = await runtime.compact_session(session_id)
        return JSONResponse({"result": result})

    async def session_info(request: Request) -> JSONResponse:
        session_id = request.query_params.get("session_id")
        info_str = await runtime.get_info(session_id)
        return JSONResponse(json.loads(info_str))

    async def chat(request: Request) -> _SSEResponse:
        body = await request.json()
        message = body["message"]
        session_id = body.get("session_id")

        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        def on_text(delta: str) -> None:
            queue.put_nowait(("text", {"delta": delta}))

        def on_tool(name: str) -> None:
            queue.put_nowait(("tool", {"name": name}))

        async def _run_chat() -> None:
            try:
                full = await runtime.chat(
                    message,
                    session_id=session_id,
                    on_text=on_text,
                    on_tool=on_tool,
                )
                queue.put_nowait(("done", {"text": full}))
            except Exception as exc:
                queue.put_nowait(("error", {"message": f"{type(exc).__name__}: {exc}"}))
            finally:
                queue.put_nowait(None)

        async def _generate() -> AsyncGenerator[str, None]:
            task = asyncio.create_task(_run_chat())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    event, data = item
                    yield _sse_line(event, data)
            finally:
                if not task.done():
                    task.cancel()

        return _SSEResponse(_generate())

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/chat", chat, methods=["POST"]),
        Route("/session/new", session_new, methods=["POST"]),
        Route("/session/compact", session_compact, methods=["POST"]),
        Route("/session/info", session_info, methods=["GET"]),
    ]

    return Starlette(routes=routes)
