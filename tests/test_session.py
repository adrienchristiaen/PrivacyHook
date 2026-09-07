from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from privacyhook.session import SessionStore, resolve_session_id


class TestResolveSessionId:
    def test_uses_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123")
        assert resolve_session_id() == "abc-123"

    def test_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        assert resolve_session_id() == "default"


class TestSessionStore:
    def test_opens_and_creates_schema(self, tmp_path: Path):
        s = SessionStore.open(tmp_path / "s.db")
        try:
            tables = {
                row[0]
                for row in s.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {"tokens", "meta"} <= tables
        finally:
            s.close()

    def test_schema_idempotent(self, tmp_path: Path):
        path = tmp_path / "s.db"
        SessionStore.open(path).close()
        s = SessionStore.open(path)
        assert s.conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0
        s.close()

    def test_put_and_get_token(self, tmp_path: Path):
        s = SessionStore.open(tmp_path / "s.db")
        try:
            s.put_token("email", "foo@bar.com", "[WALL:email:1]")
            assert s.get_original("[WALL:email:1]") == "foo@bar.com"
            assert s.get_token_for_original("foo@bar.com") == "[WALL:email:1]"
        finally:
            s.close()

    def test_put_token_unique(self, tmp_path: Path):
        s = SessionStore.open(tmp_path / "s.db")
        try:
            s.put_token("email", "foo@bar.com", "[WALL:email:1]")
            with pytest.raises(sqlite3.IntegrityError):
                s.put_token("email", "foo@bar.com", "[WALL:email:2]")
        finally:
            s.close()

    def test_meta_set_get(self, tmp_path: Path):
        s = SessionStore.open(tmp_path / "s.db")
        try:
            s.set_meta("hmac_key", "abc123")
            assert s.get_meta("hmac_key") == "abc123"
            assert s.get_meta("missing") is None
        finally:
            s.close()

    def test_next_counter(self, tmp_path: Path):
        s = SessionStore.open(tmp_path / "s.db")
        try:
            assert s.next_counter("email") == 1
            assert s.next_counter("email") == 2
            assert s.next_counter("ip") == 1
            assert s.next_counter("email") == 3
        finally:
            s.close()

    def test_concurrent_writes_ok(self, tmp_path: Path):
        path = tmp_path / "s.db"
        s1 = SessionStore.open(path)
        s2 = SessionStore.open(path)
        try:
            s1.put_token("email", "a@b.com", "[WALL:email:1]")
            s2.put_token("email", "c@d.com", "[WALL:email:2]")
            assert s1.get_original("[WALL:email:2]") == "c@d.com"
            assert s2.get_original("[WALL:email:1]") == "a@b.com"
        finally:
            s1.close()
            s2.close()
