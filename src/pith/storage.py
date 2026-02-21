"""SQLite-backed memory + session persistence."""

from __future__ import annotations

from collections.abc import Iterable
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass
class Message:
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None = None


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

    async def __aenter__(self) -> "Storage":
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
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
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
        CREATE TABLE IF NOT EXISTS extension_tools(
            name TEXT PRIMARY KEY,
            module_path TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('tool','mcp')),
            source TEXT NOT NULL,
            registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            event TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            payload TEXT
        )
        """)
        await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at)
        """)
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def log_event(self, event: str, level: str = "info", payload: dict[str, Any] | None = None) -> None:
        conn = await self.connect()
        payload_text = json.dumps(payload or {})
        await conn.execute(
            "INSERT INTO audit_log(event, level, payload) VALUES(?,?,?)",
            (event, level, payload_text),
        )
        await conn.commit()
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"event": event, "level": level, "payload": payload or {}, "ts": datetime.utcnow().isoformat() + "Z"}
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry) + "\n")

    async def set_app_state(self, key: str, value: str) -> None:
        conn = await self.connect()
        await conn.execute(
            "INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await conn.commit()

    async def get_app_state(self, key: str, default: str | None = None) -> str | None:
        conn = await self.connect()
        row = await conn.execute_fetchone("SELECT value FROM app_state WHERE key=?", (key,))
        return row[0] if row else default

    async def set_profile(self, profile_type: str, values: dict[str, str]) -> None:
        conn = await self.connect()
        updated = datetime.utcnow().isoformat() + "Z"
        for key, value in values.items():
            await conn.execute(
                "INSERT INTO profiles(profile_type,key,value,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(profile_type,key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (profile_type, key, value, updated),
            )
        await conn.commit()

    async def get_profile(self, profile_type: str) -> dict[str, str]:
        conn = await self.connect()
        rows = await conn.execute_fetchall(
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

        return all(agent.get(field) for field in required_agent) and all(user.get(field) for field in required_user)

    async def set_bootstrap_complete(self, value: bool) -> None:
        await self.set_app_state("bootstrap_complete", "1" if value else "0")

    async def all_profile_fields(self) -> dict[str, dict[str, str]]:
        return {
            "agent": await self.get_profile("agent"),
            "user": await self.get_profile("user"),
        }

    async def ensure_active_session(self) -> str:
        conn = await self.connect()
        row = await conn.execute_fetchone("SELECT value FROM app_state WHERE key='active_session_id'")
        if row:
            return str(row[0])

        session_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "." + str(int(datetime.utcnow().timestamp()))
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
        session_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "." + str(int(datetime.utcnow().timestamp()))
        conn = await self.connect()
        await conn.execute("INSERT INTO sessions(id) VALUES(?)", (session_id,))
        await conn.execute(
            "INSERT INTO app_state(key,value) VALUES('active_session_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (session_id,),
        )
        await conn.commit()
        return session_id

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        conn = await self.connect()
        cur = await conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata) VALUES(?,?,?,?)",
            (session_id, role, content, json.dumps(metadata or {})),
        )
        await conn.execute(
            "UPDATE sessions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (session_id,),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def get_recent_messages(self, session_id: str, limit: int) -> list[Message]:
        conn = await self.connect()
        rows = await conn.execute_fetchall(
            """
            SELECT role, content, created_at, metadata
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = rows[::-1]
        return [
            Message(
                role=row[0],
                content=row[1],
                created_at=row[2],
                metadata=json.loads(row[3] or "{}"),
            )
            for row in rows
        ]

    async def compact_session(self, session_id: str, keep_recent: int = 50) -> None:
        conn = await self.connect()
        count_rows = await conn.execute_fetchone(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (session_id,),
        )
        total = int(count_rows[0] if count_rows else 0)
        if total <= keep_recent:
            return

        surplus = total - keep_recent
        if surplus <= 0:
            return

        rows = await conn.execute_fetchall(
            """
            SELECT id, role, content
            FROM messages
            WHERE session_id=?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, surplus),
        )

        summary_parts: list[str] = [f"[{r[1]}] {r[2]}" for r in rows]
        summary = "\n".join(summary_parts)
        await conn.execute("INSERT INTO session_summaries(session_id, summary) VALUES(?, ?)", (session_id, summary))

        oldest = rows[-1][0]
        await conn.execute("DELETE FROM messages WHERE session_id=? AND id<=?", (session_id, oldest))
        await conn.commit()

    async def list_session_summaries(self, session_id: str) -> list[str]:
        conn = await self.connect()
        rows = await conn.execute_fetchall(
            "SELECT summary FROM session_summaries WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        )
        return [str(row[0]) for row in rows]

    async def memory_save(self, content: str, kind: str = "durable", tags: Iterable[str] | None = None, source: str = "runtime") -> int:
        conn = await self.connect()
        normalized_tags = ",".join(tags or ())
        cur = await conn.execute(
            "INSERT INTO memory_entries(content, kind, tags, source) VALUES(?,?,?,?)",
            (content, kind, normalized_tags or None, source),
        )
        await conn.commit()
        return int(cur.lastrowid)

    async def memory_search(self, query: str, limit: int = 8) -> list[MemoryEntry]:
        conn = await self.connect()

        try:
            rows = await conn.execute_fetchall(
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
            rows = await conn.execute_fetchall(
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

    async def register_tool(self, name: str, module_path: str, kind: str, source: str) -> None:
        conn = await self.connect()
        await conn.execute(
            "INSERT INTO extension_tools(name, module_path, kind, source) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET module_path=excluded.module_path, kind=excluded.kind, source=excluded.source",
            (name, module_path, kind, source),
        )
        await conn.commit()
