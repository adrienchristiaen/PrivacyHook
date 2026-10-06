"""EventStore against every backend. Postgres runs only when
PRIVACYHOOK_TEST_DATABASE_URL points at a disposable database (CI sets it)."""

from __future__ import annotations

import os
import time

import pytest

from controlplane.events_store import EventStore

PG_URL = os.environ.get("PRIVACYHOOK_TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    if request.param == "sqlite":
        s = EventStore(":memory:")
    else:
        if not PG_URL:
            pytest.skip("PRIVACYHOOK_TEST_DATABASE_URL not set")
        pytest.importorskip("psycopg")
        import psycopg
        with psycopg.connect(PG_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS events")
        s = EventStore(url=PG_URL)
    yield s
    s.close()


def _ev(user, event, tool="Bash", **kw):
    return EventStore.normalize({"user": user, "event": event, "tool": tool, "session": f"s-{user}",
                                 "cli": kw.pop("cli", "claude"), **kw})


def test_summary_counts(store):
    store.add("t1", [
        _ev("alice", "tool_call"), _ev("alice", "tool_call", "Read"),
        _ev("alice", "would_block", "Read"), _ev("alice", "redact", categories=["aws"], count=2),
        _ev("bob", "tool_call", cli="codex"), _ev("bob", "policy_block", rule="no force push"),
    ])
    s = store.summary("t1")
    assert s["totals"] == {"developers": 2, "sessions": 2, "tool_calls": 3, "blocked": 1,
                           "would_block": 1, "secrets_redacted": 2}
    alice = next(d for d in s["developers"] if d["user"] == "alice")
    assert (alice["tool_calls"], alice["would_block"], alice["secrets_redacted"]) == (2, 1, 2)
    assert s["tools"][0] == {"tool": "Bash", "calls": 2}
    assert s["rules"] == [{"rule": "no force push", "event": "policy_block", "hits": 1}]


def test_tenant_isolation(store):
    store.add("t1", [_ev("alice", "tool_call")])
    store.add("t2", [_ev("mallory", "tool_call")])
    assert [e["user"] for e in store.recent("t1")] == ["alice"]
    assert store.summary("t2")["totals"]["developers"] == 1
    assert [e["user"] for e in store.export("t1")] == ["alice"]


def test_recent_filters_by_user(store):
    store.add("t1", [_ev("alice", "tool_call"), _ev("bob", "redact", categories=["email"], count=1)])
    rows = store.recent("t1", user="bob")
    assert [(r["user"], r["categories"]) for r in rows] == [("bob", ["email"])]


def test_export_resumes_after_id(store):
    store.add("t1", [_ev("alice", "tool_call") for _ in range(5)])
    first = store.export("t1", limit=3)
    rest = store.export("t1", after_id=first[-1]["id"])
    assert len(first) == 3 and len(rest) == 2
    assert [r["id"] for r in first + rest] == sorted({r["id"] for r in first + rest})


def test_export_time_window(store):
    now = time.time()
    store.add("t1", [_ev("alice", "tool_call", ts=now - 7200), _ev("alice", "tool_call", ts=now)])
    assert len(store.export("t1", since=now - 3600)) == 1
    assert len(store.export("t1", until=now - 3600)) == 1


def test_postgres_reconnects_after_dropped_connection(store):
    if store.backend != "postgres":
        pytest.skip("postgres only")
    store.add("t1", [_ev("alice", "tool_call")])
    store._db.close()  # simulate a failover / server-side idle timeout
    store.add("t1", [_ev("bob", "tool_call")])
    assert {e["user"] for e in store.recent("t1")} == {"alice", "bob"}
