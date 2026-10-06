"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

SQLite store for the event metadata hooks send to POST /v1/events. Backs the
team dashboard (GET /) and its JSON endpoints. Stdlib sqlite3 only.

Every row carries its tenant id and every query filters on it, so one
tenant's token can never read another tenant's activity.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant     TEXT NOT NULL,
    ts         REAL NOT NULL,
    user       TEXT NOT NULL,
    team       TEXT NOT NULL,
    session    TEXT NOT NULL,
    cli        TEXT NOT NULL,
    hook       TEXT NOT NULL,
    event      TEXT NOT NULL,
    tool       TEXT NOT NULL,
    categories TEXT NOT NULL,
    count      INTEGER NOT NULL,
    rule       TEXT NOT NULL,
    mode       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_tenant_ts ON events (tenant, ts);
"""

_STR_FIELDS = ("user", "team", "session", "cli", "hook", "event", "tool", "rule", "mode")
_MAX_FIELD_LEN = 200

BLOCK_EVENTS = ("block", "policy_block")
WOULD_BLOCK_EVENTS = ("would_block", "would_policy_block")


def default_db_path() -> str:
    return os.environ.get("PRIVACYHOOK_CONTROLPLANE_DB") or str(
        Path.home() / ".local" / "share" / "privacyhook-controlplane" / "events.db"
    )


class EventStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def normalize(raw: dict) -> dict:
        """Coerce one incoming event to the stored shape. Accepts both the
        batched hook format ({event, tool, user, …}) and the original
        single-decision format ({action, tool, team, rule_id})."""
        ev = {f: str(raw.get(f) or "")[:_MAX_FIELD_LEN] for f in _STR_FIELDS}
        ev["event"] = ev["event"] or str(raw.get("action") or "unknown")[:_MAX_FIELD_LEN]
        ev["rule"] = ev["rule"] or str(raw.get("rule_id") or "")[:_MAX_FIELD_LEN]
        ev["team"] = ev["team"] or "default"
        ev["user"] = ev["user"] or "unknown"
        ev["tool"] = ev["tool"] or "—"
        try:
            ts = float(raw.get("ts") or time.time())
        except (TypeError, ValueError):
            ts = time.time()
        ev["ts"] = min(ts, time.time() + 300)  # clamp clocks running far ahead
        cats = raw.get("categories") or []
        ev["categories"] = [str(c)[:50] for c in cats][:20] if isinstance(cats, list) else []
        try:
            ev["count"] = max(0, int(raw.get("count") or 0))
        except (TypeError, ValueError):
            ev["count"] = 0
        return ev

    def add(self, tenant: str, events: list[dict]) -> None:
        rows = [
            (tenant, e["ts"], e["user"], e["team"], e["session"], e["cli"], e["hook"],
             e["event"], e["tool"], json.dumps(e["categories"]), e["count"], e["rule"], e["mode"])
            for e in events
        ]
        with self._lock:
            self._db.executemany(
                "INSERT INTO events (tenant, ts, user, team, session, cli, hook, event, tool,"
                " categories, count, rule, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self._db.commit()

    def recent(self, tenant: str, limit: int = 200, user: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events WHERE tenant = ?"
        args: list = [tenant]
        if user:
            sql += " AND user = ?"
            args.append(user)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("tenant", None)
            d["categories"] = json.loads(d["categories"] or "[]")
            out.append(d)
        return out

    def summary(self, tenant: str, hours: float = 24.0) -> dict:
        since = time.time() - hours * 3600
        q_blocks = ",".join("?" * len(BLOCK_EVENTS))
        q_would = ",".join("?" * len(WOULD_BLOCK_EVENTS))
        with self._lock:
            totals = self._db.execute(
                f"""SELECT
                      COUNT(DISTINCT user)                                   AS developers,
                      COUNT(DISTINCT session)                                AS sessions,
                      SUM(event = 'tool_call')                               AS tool_calls,
                      SUM(event IN ({q_blocks}))                             AS blocked,
                      SUM(event IN ({q_would}))                              AS would_block,
                      SUM(CASE WHEN event = 'redact' THEN count ELSE 0 END)  AS secrets_redacted
                    FROM events WHERE tenant = ? AND ts >= ?""",
                [*BLOCK_EVENTS, *WOULD_BLOCK_EVENTS, tenant, since],
            ).fetchone()
            people = self._db.execute(
                f"""SELECT user,
                      MAX(team)                                              AS team,
                      GROUP_CONCAT(DISTINCT cli)                             AS clis,
                      COUNT(DISTINCT session)                                AS sessions,
                      SUM(event = 'tool_call')                               AS tool_calls,
                      SUM(event IN ({q_blocks}))                             AS blocked,
                      SUM(event IN ({q_would}))                              AS would_block,
                      SUM(CASE WHEN event = 'redact' THEN count ELSE 0 END)  AS secrets_redacted,
                      MAX(ts)                                                AS last_seen
                    FROM events WHERE tenant = ? AND ts >= ?
                    GROUP BY user ORDER BY last_seen DESC""",
                [*BLOCK_EVENTS, *WOULD_BLOCK_EVENTS, tenant, since],
            ).fetchall()
            tools = self._db.execute(
                """SELECT tool, COUNT(*) AS calls FROM events
                   WHERE tenant = ? AND ts >= ? AND event = 'tool_call'
                   GROUP BY tool ORDER BY calls DESC LIMIT 10""",
                [tenant, since],
            ).fetchall()
            rules = self._db.execute(
                f"""SELECT rule, event, COUNT(*) AS hits FROM events
                    WHERE tenant = ? AND ts >= ? AND rule != ''
                    GROUP BY rule, event ORDER BY hits DESC LIMIT 10""",
                [tenant, since],
            ).fetchall()
        return {
            "hours": hours,
            "totals": {k: (totals[k] or 0) for k in totals.keys()},
            "developers": [dict(r) for r in people],
            "tools": [dict(r) for r in tools],
            "rules": [dict(r) for r in rules],
        }
