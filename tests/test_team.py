from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from privacyhook import team
from privacyhook.remote_policy import RemotePolicySource

ROOT = Path(__file__).parent.parent


@pytest.fixture
def control_plane(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    from controlplane import server as cp_server
    from controlplane.events_store import EventStore

    # Tenants file rather than _TOKEN env: server and client share this
    # process's env, and the client must not inherit the server's token.
    tenants = tmp_path / "tenants.yaml"
    tenants.write_text(
        f"- id: default\n  token: team-token\n  policy_path: {tmp_path / 'missing-policy.yaml'}\n"
    )
    monkeypatch.setenv("PRIVACYHOOK_CONTROLPLANE_TENANTS_PATH", str(tenants))
    cp_server._event_store = EventStore(":memory:")
    cp_server._rate_limit_hits.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), cp_server._Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", cp_server
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def client_env(tmp_path, monkeypatch):
    for var in ("PRIVACYHOOK_CONTROLPLANE_URL", "PRIVACYHOOK_CONTROLPLANE_TOKEN", "PRIVACYHOOK_USER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PRIVACYHOOK_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("PRIVACYHOOK_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PRIVACYHOOK_TEAM_SYNC", "1")
    return tmp_path


def test_not_in_team_records_nothing(client_env):
    team.record({"event": "tool_call", "tool": "Bash"})
    assert not team.outbox_path().exists()


def test_sanitize_keeps_only_metadata():
    out = team.sanitize(
        {"event": "would_block", "tool": "Read", "target": "/home/me/.env",
         "reason": "filename '.env' is sensitive", "hmac": "x", "count": 0},
        user="alice",
    )
    assert "target" not in out and "reason" not in out and "hmac" not in out and "rule" not in out
    assert out["user"] == "alice"
    rule = team.sanitize({"event": "would_policy_block", "reason": "force push needs a human"}, user="a")
    assert rule["rule"] == "force push needs a human"


def test_join_then_events_reach_dashboard(client_env, control_plane):
    url, cp_server = control_plane
    from privacyhook.cli import main

    assert main(["join", url, "--token", "team-token", "--name", "alice", "--no-install"]) == 0
    assert json.loads(team.config_path().read_text())["user"] == "alice"
    assert RemotePolicySource().configured

    team.record({"ts": 1.0, "session": "s1", "cli": "claude", "hook": "pre_tool_use",
                 "event": "tool_call", "tool": "Bash", "categories": [], "count": 0})
    events = cp_server._store().recent("default")
    assert [(e["user"], e["event"], e["tool"]) for e in events] == [("alice", "tool_call", "Bash")]
    assert team.pending_count() == 0


def test_join_rejects_bad_token(client_env, control_plane):
    url, _ = control_plane
    from privacyhook.cli import main

    assert main(["join", url, "--token", "nope", "--no-install"]) == 1
    assert not team.config_path().exists()


def test_unreachable_server_keeps_events_queued(client_env):
    team.save_config("http://127.0.0.1:9", "t", "alice")  # port 9: discard, nothing listens
    team.record({"event": "tool_call", "tool": "Bash"})
    team.record({"event": "redact", "tool": "Bash", "categories": ["openai_key"], "count": 1})
    assert team.pending_count() == 2


def test_leave_clears_config(client_env):
    team.save_config("http://127.0.0.1:9", "t", "alice")
    assert team.clear_config()
    assert team.load_config() is None


def test_hook_sends_tool_call_and_decision(client_env, control_plane, tmp_path):
    url, cp_server = control_plane
    team.save_config(url, "team-token", "alice")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("SECRET=1\n")
    env = {k: v for k, v in os.environ.items() if k != "PRIVACYHOOK_MODE"}
    env.update({"PYTHONPATH": str(ROOT), "CLAUDE_SESSION_ID": "sess-1",
                "PRIVACYHOOK_SESSION_ROOT": str(tmp_path / "sess"),
                "PRIVACYHOOK_POLICY_PATH": str(tmp_path / "policy.json")})
    proc = subprocess.run(
        [sys.executable, "-m", "privacyhook.hooks.pre_tool_use"],
        input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": ".env"}}),
        capture_output=True, text=True, env=env, cwd=str(ws), timeout=15,
    )
    assert proc.returncode == 0, proc.stderr  # observe mode
    events = cp_server._store().recent("default")
    assert {e["event"] for e in events} == {"tool_call", "would_block"}
    assert all(e["user"] == "alice" for e in events)
    assert not any(".env" in json.dumps(e) for e in events)  # path never leaves the machine
