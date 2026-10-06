"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

Store for the event metadata hooks send to POST /v1/events. Backs the team
dashboard (GET /) and its JSON endpoints.

Two backends behind one class:
- SQLite (default, stdlib): one file, one replica. Fine for a team.
- Postgres, when PRIVACYHOOK_CONTROLPLANE_DATABASE_URL=postgresql://… is set:
  run several replicas behind a load balancer (needs `psycopg`).

Queries are written once with `?` placeholders and portable SQL; the
Postgres backend swaps the placeholder style.

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

_COLUMNS = """
    tenant     TEXT NOT NULL,
    ts         DOUBLE PRECISION NOT NULL,
    "user"     TEXT NOT NULL,
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
"""
_SCHEMA = {
    "sqlite": [
        f"CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, {_COLUMNS})",
        "CREATE INDEX IF NOT EXISTS events_tenant_ts ON events (tenant, ts)",
    ],
    "postgres": [
        f"CREATE TABLE IF NOT EXISTS events (id BIGSERIAL PRIMARY KEY, {_COLUMNS})",
        "CREATE INDEX IF NOT EXISTS events_tenant_ts ON events (tenant, ts)",
    ],
}

_STR_FIELDS = ("user", "team", "session", "cli", "hook", "event", "tool", "rule", "mode")
_MAX_FIELD_LEN = 200

BLOCK_EVENTS = ("block", "policy_block")
WOULD_BLOCK_EVENTS = ("would_block", "would_policy_block")


def _count_if(cond: str) -> str:
    return f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END)"


def database_url() -> str | None:
    url = os.environ.get("PRIVACYHOOK_CONTROLPLANE_DATABASE_URL") or ""
    return url if url.startswith(("postgres://", "postgresql://")) else None


def default_db_path() -> str:
    return os.environ.get("PRIVACYHOOK_CONTROLPLANE_DB") or str(
        Path.home() / ".local" / "share" / "privacyhook-controlplane" / "events.db"
    )


class EventStore:
    def __init__(self, path: str | None = None, *, url: str | None = None):
        self._lock = threading.Lock()
        url = url if url is not None else (None if path else database_url())
        if url:
            import psycopg  # optional: pip install "psycopg[binary]"
            from psycopg.rows import dict_row

            self.backend = "postgres"
            self.path = url
            self._connect = lambda: psycopg.connect(url, autocommit=True, row_factory=dict_row)
            self._db = self._connect()
        else:
            self.backend = "sqlite"
            self.path = path or default_db_path()
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
        try:
            self._create_schema()
        except Exception:
            # Several replicas starting together can race on CREATE TABLE IF
            # NOT EXISTS in Postgres; the loser just retries once.
            time.sleep(0.5)
            self._reconnect()
            self._create_schema()

    def _create_schema(self) -> None:
        for stmt in _SCHEMA[self.backend]:
            self._db.execute(stmt)
        self._commit()

    def _reconnect(self) -> None:
        if self.backend == "postgres":
            try:
                self._db.close()
            except Exception:
                pass
            self._db = self._connect()

    def _with_retry(self, fn):
        """Run fn(); on a dropped Postgres connection (failover, restart,
        idle timeout) reconnect once and retry."""
        if self.backend != "postgres":
            return fn()
        import psycopg
        try:
            return fn()
        except psycopg.OperationalError:
            self._reconnect()
            return fn()

    def close(self) -> None:
        self._db.close()

    def _commit(self) -> None:
        if self.backend == "sqlite":
            self._db.commit()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.backend == "postgres" else sql

    def _all(self, sql: str, args: list) -> list[dict]:
        return self._with_retry(
            lambda: [dict(r) for r in self._db.execute(self._sql(sql), args).fetchall()]
        )

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
        sql = self._sql(
            'INSERT INTO events (tenant, ts, "user", team, session, cli, hook, event, tool,'
            " categories, count, rule, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        def insert():
            if self.backend == "postgres":
                with self._db.cursor() as cur:
                    cur.executemany(sql, rows)
            else:
                self._db.executemany(sql, rows)
            self._commit()

        with self._lock:
            self._with_retry(insert)

    def recent(self, tenant: str, limit: int = 200, user: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events WHERE tenant = ?"
        args: list = [tenant]
        if user:
            sql += ' AND "user" = ?'
            args.append(user)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._all(sql, args)
        out = []
        for d in rows:
            d.pop("tenant", None)
            d["categories"] = json.loads(d["categories"] or "[]")
            out.append(d)
        return out

    def summary(self, tenant: str, hours: float = 24.0) -> dict:
        since = time.time() - hours * 3600
        blocks = ",".join("?" * len(BLOCK_EVENTS))
        would = ",".join("?" * len(WOULD_BLOCK_EVENTS))
        # Positional params: the two IN lists, then tenant and since.
        args = [*BLOCK_EVENTS, *WOULD_BLOCK_EVENTS, tenant, since]
        agg = f"""
              {_count_if("event = 'tool_call'")}                      AS tool_calls,
              {_count_if(f"event IN ({blocks})")}                     AS blocked,
              {_count_if(f"event IN ({would})")}                      AS would_block,
              SUM(CASE WHEN event = 'redact' THEN count ELSE 0 END)   AS secrets_redacted"""
        clis = "string_agg(DISTINCT cli, ',')" if self.backend == "postgres" else "GROUP_CONCAT(DISTINCT cli)"
        with self._lock:
            totals = self._all(
                f"""SELECT COUNT(DISTINCT "user") AS developers, COUNT(DISTINCT session) AS sessions, {agg}
                    FROM events WHERE tenant = ? AND ts >= ?""",
                args,
            )[0]
            people = self._all(
                f"""SELECT "user" AS user, MAX(team) AS team, {clis} AS clis,
                      COUNT(DISTINCT session) AS sessions, {agg}, MAX(ts) AS last_seen
                    FROM events WHERE tenant = ? AND ts >= ?
                    GROUP BY "user" ORDER BY last_seen DESC""",
                args,
            )
            tools = self._all(
                """SELECT tool, COUNT(*) AS calls FROM events
                   WHERE tenant = ? AND ts >= ? AND event = 'tool_call'
                   GROUP BY tool ORDER BY calls DESC, tool LIMIT 10""",
                [tenant, since],
            )
            rules = self._all(
                """SELECT rule, event, COUNT(*) AS hits FROM events
                   WHERE tenant = ? AND ts >= ? AND rule != ''
                   GROUP BY rule, event ORDER BY hits DESC LIMIT 10""",
                [tenant, since],
            )
        return {
            "hours": hours,
            "totals": {k: int(v or 0) for k, v in totals.items()},
            "developers": [_ints(r) for r in people],
            "tools": [_ints(r) for r in tools],
            "rules": [_ints(r) for r in rules],
        }

    def export(self, tenant: str, since: float = 0.0, until: float | None = None,
               after_id: int = 0, limit: int = 10000) -> list[dict]:
        """Rows in id order, for loading into a warehouse. `after_id` lets a
        nightly job resume exactly where the previous run stopped."""
        sql = "SELECT * FROM events WHERE tenant = ? AND id > ? AND ts >= ?"
        args: list = [tenant, after_id, since]
        if until is not None:
            sql += " AND ts < ?"
            args.append(until)
        sql += " ORDER BY id LIMIT ?"
        args.append(max(1, min(limit, 100000)))
        with self._lock:
            rows = self._all(sql, args)
        for d in rows:
            d.pop("tenant", None)
            d["categories"] = json.loads(d["categories"] or "[]")
        return rows


def _ints(row: dict) -> dict:
    """Postgres returns SUM() as Decimal; keep the JSON plain numbers."""
    from decimal import Decimal
    return {k: (int(v) if isinstance(v, Decimal) else v) for k, v in row.items()}
