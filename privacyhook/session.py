"""SQLite-backed session store.

One database per Claude Code session, lives under
`$PRIVACYHOOK_SESSION_ROOT/<session_id>/session.db` (default root:
`/tmp/privacyhook`). Stores reversible redaction tokens, per-category
counters, and meta (audit HMAC key, workspace scan cache).
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    original TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token ON tokens(token);
CREATE INDEX IF NOT EXISTS idx_category ON tokens(category);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS counters (
    category TEXT PRIMARY KEY,
    n INTEGER NOT NULL
);
"""


def resolve_session_id() -> str:
    """Return the active Claude Code session id, or `default`."""
    return os.environ.get("CLAUDE_SESSION_ID") or "default"


def session_root() -> Path:
    """Root directory holding per-session DBs."""
    return Path(os.environ.get("PRIVACYHOOK_SESSION_ROOT") or "/tmp/privacyhook")


def session_db_path(session_id: str | None = None) -> Path:
    sid = session_id or resolve_session_id()
    return session_root() / sid / "session.db"


@dataclass
class SessionStore:
    """Thin wrapper around a per-session SQLite connection.

    Open via `SessionStore.open(path)`; close via `.close()`. The connection
    uses WAL mode so multiple processes (e.g. hooks running in parallel) can
    read and write concurrently without locking each other out.
    """

    conn: sqlite3.Connection
    path: Path

    @classmethod
    def open(cls, path: Path | str | None = None) -> "SessionStore":
        p = Path(path) if path is not None else session_db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(p),
            timeout=5.0,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        return cls(conn=conn, path=p)

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- tokens --------------------------------------------------------

    def put_token(self, category: str, original: str, token: str) -> None:
        self.conn.execute(
            "INSERT INTO tokens(category, original, token, created_at)"
            " VALUES (?, ?, ?, ?)",
            (category, original, token, time.time()),
        )

    def get_original(self, token: str) -> str | None:
        row = self.conn.execute(
            "SELECT original FROM tokens WHERE token = ?", (token,)
        ).fetchone()
        return row[0] if row else None

    def get_token_for_original(self, original: str) -> str | None:
        row = self.conn.execute(
            "SELECT token FROM tokens WHERE original = ?", (original,)
        ).fetchone()
        return row[0] if row else None

    def all_tokens(self) -> list[tuple[str, str, str]]:
        return [
            (cat, orig, tok)
            for cat, orig, tok in self.conn.execute(
                "SELECT category, original, token FROM tokens ORDER BY id"
            )
        ]

    # ---- counters ------------------------------------------------------

    def next_counter(self, category: str) -> int:
        self.conn.execute(
            "INSERT INTO counters(category, n) VALUES (?, 1)"
            " ON CONFLICT(category) DO UPDATE SET n = n + 1",
            (category,),
        )
        row = self.conn.execute(
            "SELECT n FROM counters WHERE category = ?", (category,)
        ).fetchone()
        return int(row[0])

    # ---- meta ----------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
