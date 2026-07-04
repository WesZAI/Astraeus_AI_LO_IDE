# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""database_manager.py

Simple SQLite-backed DatabaseManager with a small convenience API used by
the GUI. Designed for local storage inside the workspace and safe to use
from a single-threaded GUI. For multi-threaded use see the notes below.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable, Optional, Sequence, Tuple


class DatabaseManager:
    """File-backed manager. If given a path ending in `.json` it acts as a
    simple JSON file manager. Otherwise it falls back to a lightweight
    SQLite-backed manager (via `SQLiteMemoryManager`).

    The class provides minimal helpers sufficient for the GUI's usage.
    """

    def __init__(self, db_path: str | Path = "app_data.db") -> None:
        self.db_path = Path(db_path)
        if self.db_path.suffix.lower() == ".json":
            self._mode = "json"
            self._ensure_json_exists()
        else:
            self._mode = "sqlite"
            self._sqlite = SQLiteMemoryManager(self.db_path)

    # --- JSON helpers ---
    def _ensure_json_exists(self) -> None:
        if not self.db_path.exists():
            self.db_path.write_text('{"messages": []}', encoding="utf-8")

    def load_json(self) -> Any:
        return json_load(self.db_path)

    def save_json(self, data: Any) -> None:
        self.db_path.write_text(json_dumps(data), encoding="utf-8")

    @property
    def chat_history(self) -> list:
        if self._mode != "json":
            raise NotImplementedError("chat_history is only available for json mode")
        data = self.load_json()
        return data.get("messages", [])

    def add_message_to_history(self, user_message: str, assistant_response: str) -> None:
        if self._mode != "json":
            raise NotImplementedError("add_message_to_history is only available for json mode")
        data = self.load_json()
        messages = data.get("messages", [])
        messages.append({"user": user_message, "assistant": assistant_response})
        data["messages"] = messages
        self.save_json(data)

    # --- SQLite passthrough ---
    def connect(self) -> None:
        if self._mode == "sqlite":
            self._sqlite.connect()

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None):
        if self._mode == "sqlite":
            return self._sqlite.execute(sql, params)
        raise NotImplementedError("execute is only available for sqlite mode")

    def fetchall(self, sql: str, params: Optional[Iterable[Any]] = None):
        if self._mode == "sqlite":
            return self._sqlite.fetchall(sql, params)
        raise NotImplementedError("fetchall is only available for sqlite mode")


def json_load(path: Path) -> Any:
    import json

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


class SQLiteMemoryManager:
    """Small helper providing a simple key/value store backed by SQLite.

    Intended for the `memory.sqlite3` file used by the GUI.
    """

    def __init__(self, db_path: str | Path = "memory.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        if self.conn:
            return
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        assert self.conn is not None
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS global_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT UNIQUE NOT NULL,
                simple_variants TEXT,
                theme TEXT,
                intent TEXT,
                sentiment REAL DEFAULT 0.5,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS user_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                simple_text TEXT NOT NULL,
                expanded_text TEXT NOT NULL,
                confidence REAL DEFAULT 0.9,
                last_used TEXT,
                UNIQUE(user_id, simple_text)
            );
            CREATE TABLE IF NOT EXISTS occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                pattern_id INTEGER,
                speaker TEXT,
                timestamp TEXT
            );
            """
        )
        self.conn.commit()

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> sqlite3.Cursor:
        self.connect()
        cur = self.conn.cursor()
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        self.conn.commit()
        return cur

    def fetchall(self, sql: str, params: Optional[Iterable[Any]] = None) -> list[sqlite3.Row]:
        cur = self.execute(sql, params)
        return cur.fetchall()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        rows = self.fetchall("SELECT value FROM kv_store WHERE key = ?", (key,))
        if not rows:
            return default
        return rows[0][0]

    def set(self, key: str, value: str) -> None:
        self.execute("REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, value))

    def load_all(self) -> dict:
        rows = self.fetchall("SELECT key, value FROM kv_store")
        return {r["key"]: r["value"] for r in rows}

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


__all__ = ["DatabaseManager", "SQLiteMemoryManager"]
