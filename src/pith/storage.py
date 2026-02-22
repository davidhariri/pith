"""SQLite-backed memory + session persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter


@dataclass
class MemoryEntry:
    id: int
    content: str
    kind: str
    tags: str | None
    source: str
    created_at: str
    updated_at: str


class Storage:
    def __init__(self, db_path: str | Path, log_path: Path | None = None):
        self.db_path = Path(db_path)
        self.log_path = log_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Storage:
        await self.connect()
        await self.ensure_schema()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    async def ensure_schema(self) -> None:
        conn = await self.connect()
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles(
            profile_type TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            PRIMARY KEY (profile_type, key)
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'episodic',
            tags TEXT,
            source TEXT NOT NULL DEFAULT 'runtime',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted INTEGER NOT NULL DEFAULT 0
        )
        """)
        await conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
        USING fts5(content, content='memory_entries', content_rowid='id')
        """)
        await conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_entries
        BEGIN
            INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
        END;
        """)
        await conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_entries
        BEGIN
            DELETE FROM memory_fts WHERE rowid = old.id;
        END;
        """)
        await conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_entries
        BEGIN
            UPDATE memory_fts SET content = new.content WHERE rowid = new.id;
        END;
        """)
        await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_session_created
        ON messages(session_id, created_at)
        """)

        # Schema migration: drop tables with stale schemas (early-stage, no data to preserve)
        for table, required_col in [("messages", "message_json")]:
            cols = await self._fetchall(f"PRAGMA table_info({table})")
            col_names = {row[1] for row in cols}
            if cols and required_col not in col_names:
                await conn.execute(f"DROP TABLE {table}")
                await conn.execute("""
                CREATE TABLE messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """)

        await conn.commit()

    async def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        conn = await self.connect()
        cursor = await conn.execute(query, params)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        conn = await self.connect()
        cursor = await conn.execute(query, params)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # -- Logging (JSONL only) --

    async def log_event(
        self, event: str, level: str = "info", payload: dict[str, Any] | None = None
    ) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "event": event,
            "level": level,
            "payload": payload or {},
            "ts": datetime.now(UTC).isoformat(),
        }
        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry) + "\n")

    # -- App state --

    async def set_app_state(self, key: str, value: str) -> None:
        conn = await self.connect()
        await conn.execute(
            "INSERT INTO app_state(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await conn.commit()

    async def get_app_state(self, key: str, default: str | None = None) -> str | None:
        row = await self._fetchone("SELECT value FROM app_state WHERE key=?", (key,))
        return row[0] if row else default

    # -- Profiles --

    async def set_profile(self, profile_type: str, key: str, value: str) -> None:
        conn = await self.connect()
        updated = datetime.now(UTC).isoformat()
        await conn.execute(
            "INSERT INTO profiles(profile_type,key,value,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(profile_type,key) DO UPDATE SET "
            "value=excluded.value, updated_at=excluded.updated_at",
            (profile_type, key, value, updated),
        )
        await conn.commit()

    async def get_profile(self, profile_type: str) -> dict[str, str]:
        rows = await self._fetchall(
            "SELECT key, value FROM profiles WHERE profile_type=? ORDER BY key",
            (profile_type,),
        )
        return {row[0]: row[1] for row in rows}

    async def get_bootstrap_state(self) -> bool:
        complete_raw = await self.get_app_state("bootstrap_complete", "0")
        if complete_raw == "1":
            return True

        agent = await self.get_profile("agent")
        user = await self.get_profile("user")
        required_agent = ("name", "nature")
        required_user = ("name",)

        return all(agent.get(f) for f in required_agent) and all(user.get(f) for f in required_user)

    async def set_bootstrap_complete(self, value: bool) -> None:
        await self.set_app_state("bootstrap_complete", "1" if value else "0")

    async def all_profile_fields(self) -> dict[str, dict[str, str]]:
        return {
            "agent": await self.get_profile("agent"),
            "user": await self.get_profile("user"),
        }

    # -- Sessions --

    async def ensure_active_session(self) -> str:
        conn = await self.connect()
        row = await self._fetchone("SELECT value FROM app_state WHERE key='active_session_id'")
        if row:
            return str(row[0])

        now = datetime.now(UTC)
        session_id = now.strftime("%Y%m%dT%H%M%S") + "." + str(int(now.timestamp()))
        await conn.execute("INSERT INTO sessions(id) VALUES(?)", (session_id,))
        await conn.execute(
            "INSERT INTO app_state(key,value) VALUES('active_session_id',?)",
            (session_id,),
        )
        await conn.commit()
        return session_id

    async def set_active_session(self, session_id: str) -> None:
        await self.set_app_state("active_session_id", session_id)

    async def new_session(self) -> str:
        now = datetime.now(UTC)
        session_id = now.strftime("%Y%m%dT%H%M%S") + "." + str(int(now.timestamp()))
        conn = await self.connect()
        await conn.execute("INSERT INTO sessions(id) VALUES(?)", (session_id,))
        await conn.execute(
            "INSERT INTO app_state(key,value) VALUES('active_session_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (session_id,),
        )
        await conn.commit()
        return session_id

    # -- Messages (ModelMessage serialization) --

    async def append_messages(self, session_id: str, messages: list[ModelMessage]) -> None:
        conn = await self.connect()
        adapter = ModelMessagesTypeAdapter
        for msg in messages:
            serialized = json.dumps(adapter.dump_python([msg], mode="json")[0])
            await conn.execute(
                "INSERT INTO messages(session_id, message_json) VALUES(?,?)",
                (session_id, serialized),
            )
        await conn.execute(
            "UPDATE sessions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (session_id,),
        )
        await conn.commit()

    async def get_message_history(self, session_id: str, limit: int = 20) -> list[ModelMessage]:
        rows = await self._fetchall(
            """
            SELECT message_json
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = rows[::-1]  # chronological order
        raw_list = [json.loads(row[0]) for row in rows]
        return ModelMessagesTypeAdapter.validate_python(raw_list)

    # -- Compaction --

    async def compact_session(self, session_id: str, keep_recent: int = 50) -> None:
        conn = await self.connect()
        count_row = await self._fetchone(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (session_id,),
        )
        total = int(count_row[0] if count_row else 0)
        if total <= keep_recent:
            return

        surplus = total - keep_recent
        if surplus <= 0:
            return

        rows = await self._fetchall(
            """
            SELECT id, message_json
            FROM messages
            WHERE session_id=?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, surplus),
        )

        summary_parts: list[str] = [str(r[1])[:200] for r in rows]
        summary = "\n".join(summary_parts)
        await conn.execute(
            "INSERT INTO session_summaries(session_id, summary) VALUES(?, ?)",
            (session_id, summary),
        )

        oldest = rows[-1][0]
        await conn.execute(
            "DELETE FROM messages WHERE session_id=? AND id<=?", (session_id, oldest)
        )
        await conn.commit()

    async def list_session_summaries(self, session_id: str) -> list[str]:
        rows = await self._fetchall(
            "SELECT summary FROM session_summaries WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        )
        return [str(row[0]) for row in rows]

    # -- Memory (FTS5) --

    async def memory_save(
        self,
        content: str,
        kind: str = "durable",
        tags: Iterable[str] | None = None,
        source: str = "runtime",
    ) -> int:
        conn = await self.connect()
        normalized_tags = ",".join(tags or ())
        cur = await conn.execute(
            "INSERT INTO memory_entries(content, kind, tags, source) VALUES(?,?,?,?)",
            (content, kind, normalized_tags or None, source),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def memory_search(self, query: str, limit: int = 8) -> list[MemoryEntry]:
        try:
            rows = await self._fetchall(
                """
                SELECT m.id, m.content, m.kind, m.tags, m.source, m.created_at, m.updated_at
                FROM memory_fts f
                JOIN memory_entries m ON m.id = f.rowid
                WHERE m.deleted = 0 AND f MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
        except sqlite3.OperationalError:
            rows = await self._fetchall(
                """
                SELECT id, content, kind, tags, source, created_at, updated_at
                FROM memory_entries
                WHERE deleted = 0 AND content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            )

        return [
            MemoryEntry(
                id=int(row[0]),
                content=row[1],
                kind=row[2],
                tags=row[3],
                source=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]
