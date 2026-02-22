"""Thin HTTP client for the pith API server."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from .constants import DEFAULT_API_PORT


class PithClient:
    """Async client that talks to a running pith server."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or f"http://localhost:{DEFAULT_API_PORT}"
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=120)

    async def close(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict:
        resp = await self._http.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def new_session(self) -> str:
        resp = await self._http.post("/session/new", json={})
        resp.raise_for_status()
        return resp.json()["session_id"]

    async def compact_session(self, session_id: str | None = None) -> str:
        resp = await self._http.post("/session/compact", json={"session_id": session_id})
        resp.raise_for_status()
        return resp.json()["result"]

    async def get_info(self, session_id: str | None = None) -> dict:
        params = {}
        if session_id:
            params["session_id"] = session_id
        resp = await self._http.get("/session/info", params=params)
        resp.raise_for_status()
        return resp.json()

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str], None] | None = None,
    ) -> str:
        """Send a message and consume the SSE stream. Returns the full response text."""
        body: dict = {"message": message}
        if session_id:
            body["session_id"] = session_id

        full_text = ""
        async with self._http.stream("POST", "/chat", json=body) as resp:
            resp.raise_for_status()
            event_type = ""
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event_type == "text":
                        if on_text:
                            on_text(data["delta"])
                    elif event_type == "tool":
                        if on_tool:
                            on_tool(data["name"])
                    elif event_type == "done":
                        full_text = data["text"]
                    elif event_type == "error":
                        raise RuntimeError(data["message"])

        return full_text
