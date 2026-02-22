"""Telegram channel adapter."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from ..runtime import Runtime


async def run_telegram(runtime: Runtime) -> None:
    cfg = runtime.cfg.telegram
    token = os.environ.get(cfg.bot_token_env)
    if not token:
        print(f"telegram token not set in {cfg.bot_token_env}")
        return

    base_url = f"https://api.telegram.org/bot{token}"
    client = httpx.AsyncClient(base_url=base_url, timeout=60)
    offset = 0

    while True:
        params: dict[str, Any] = {
            "offset": offset,
            "timeout": 30,
            "allowed_updates": ["message"],
        }
        resp = await client.get("/getUpdates", params=params)
        data = resp.json()
        if not data.get("ok"):
            print(f"telegram error: {data}")
            await asyncio.sleep(2)
            continue

        updates = data.get("result", [])
        for update in updates:
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            text = message.get("text")
            if not text:
                continue

            if text.startswith("/"):
                command = text.strip().lower()
                if command == "/new":
                    new_session = await runtime.new_session()
                    await send_message(client, message["chat"]["id"], f"new session {new_session}")
                    continue
                if command == "/compact":
                    info = await runtime.compact_session()
                    await send_message(client, message["chat"]["id"], info)
                    continue
                if command == "/info":
                    info = await runtime.get_info()
                    await send_message(client, message["chat"]["id"], info)
                    continue

            session_id = await runtime.storage.ensure_active_session()
            reply = await runtime.chat(text, session_id=session_id)
            await send_message(client, message["chat"]["id"], reply)

        await asyncio.sleep(0.25)


async def send_message(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    await client.post("/sendMessage", json={"chat_id": chat_id, "text": text})
