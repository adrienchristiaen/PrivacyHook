from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from controlplane import server as cp_server
from controlplane.events_store import EventStore


@pytest.fixture
def running_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "- id: a\n  tool: Bash\n  match_type: command_regex\n  pattern: rm -rf\n  action: block\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PRIVACYHOOK_CONTROLPLANE_POLICY_PATH", str(policy_path))
    monkeypatch.setenv("PRIVACYHOOK_CONTROLPLANE_TOKEN", "test-token")

    cp_server._policy_cache.update(mtime=None, version="", rules_json=[])
    cp_server._decision_counts.clear()
    cp_server._event_store = EventStore(":memory:")
    cp_server._rate_limit_hits.clear()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), cp_server._Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", policy_path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url: str, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(url: str, payload: dict, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_healthz_no_auth(running_server):
    base, _ = running_server
    status, body = _get(f"{base}/healthz")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_policy_requires_token(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/v1/policy")
    assert status == 401


def test_policy_rejects_wrong_token(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/v1/policy", token="wrong")
    assert status == 401


def test_policy_returns_rules_with_valid_token(running_server):
    base, _ = running_server
    status, body = _get(f"{base}/v1/policy", token="test-token")
    assert status == 200
    data = json.loads(body)
    assert data["rules"][0]["id"] == "a"
    assert len(data["version"]) == 16


def test_version_changes_when_file_mtime_changes(running_server):
    base, policy_path = running_server
    _, body1 = _get(f"{base}/v1/policy", token="test-token")
    v1 = json.loads(body1)["version"]

    time.sleep(0.05)
    policy_path.write_text(
        "- id: b\n  tool: Bash\n  match_type: command_regex\n  pattern: other\n  action: warn\n",
        encoding="utf-8",
    )
    _, body2 = _get(f"{base}/v1/policy", token="test-token")
    v2 = json.loads(body2)["version"]
    assert v1 != v2


def test_events_requires_token(running_server):
    base, _ = running_server
    status, _ = _post(f"{base}/v1/events", {"action": "block", "tool": "Bash", "team": "x"})
    assert status == 401


def test_events_increments_metrics(running_server):
    base, _ = running_server
    status, _ = _post(
        f"{base}/v1/events",
        {"action": "block", "tool": "Bash", "team": "sec"},
        token="test-token",
    )
    assert status == 200

    _, metrics_body = _get(f"{base}/metrics")
    text = metrics_body.decode("utf-8")
    assert (
        'privacyhook_policy_decisions_total{tenant="default",action="block",tool="Bash",team="sec"} 1'
        in text
    )


def test_metrics_no_auth_required(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/metrics")
    assert status == 200


def test_unknown_path_404(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/nope")
    assert status == 404


@pytest.fixture
def multi_tenant_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy_a = tmp_path / "a.yaml"
    policy_a.write_text(
        "- id: a-rule\n  tool: Bash\n  match_type: command_regex\n  pattern: rm -rf\n  action: block\n",
        encoding="utf-8",
    )
    policy_b = tmp_path / "b.yaml"
    policy_b.write_text(
        "- id: b-rule\n  tool: Bash\n  match_type: command_regex\n  pattern: curl\n  action: warn\n",
        encoding="utf-8",
    )
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        f"- id: acme\n  token: token-a\n  policy_path: {policy_a}\n"
        f"- id: globex\n  token: token-b\n  policy_path: {policy_b}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PRIVACYHOOK_CONTROLPLANE_TOKEN", raising=False)
    monkeypatch.delenv("PRIVACYHOOK_CONTROLPLANE_POLICY_PATH", raising=False)
    monkeypatch.setenv("PRIVACYHOOK_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    cp_server._policy_cache.clear()
    cp_server._decision_counts.clear()
    cp_server._event_store = EventStore(":memory:")
    cp_server._rate_limit_hits.clear()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), cp_server._Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_multi_tenant_policy_isolation(multi_tenant_server):
    base = multi_tenant_server
    status_a, body_a = _get(f"{base}/v1/policy", token="token-a")
    status_b, body_b = _get(f"{base}/v1/policy", token="token-b")
    assert status_a == 200 and status_b == 200
    assert json.loads(body_a)["rules"][0]["id"] == "a-rule"
    assert json.loads(body_b)["rules"][0]["id"] == "b-rule"


def test_multi_tenant_unknown_token_rejected(multi_tenant_server):
    base = multi_tenant_server
    status, _ = _get(f"{base}/v1/policy", token="not-a-real-token")
    assert status == 401


def test_multi_tenant_metrics_isolation(multi_tenant_server):
    base = multi_tenant_server
    _post(f"{base}/v1/events", {"action": "block", "tool": "Bash", "team": "x"}, token="token-a")
    _post(f"{base}/v1/events", {"action": "warn", "tool": "Bash", "team": "y"}, token="token-b")

    _, metrics_body = _get(f"{base}/metrics")
    text = metrics_body.decode("utf-8")
    assert 'tenant="acme",action="block",tool="Bash",team="x"' in text
    assert 'tenant="globex",action="warn",tool="Bash",team="y"' in text


def test_events_rate_limited_after_threshold(running_server, monkeypatch: pytest.MonkeyPatch):
    base, _ = running_server
    monkeypatch.setenv("PRIVACYHOOK_CONTROLPLANE_EVENTS_RATE_LIMIT", "3")

    for _ in range(3):
        status, _ = _post(
            f"{base}/v1/events", {"action": "block", "tool": "Bash", "team": "sec"}, token="test-token",
        )
        assert status == 200

    status, body = _post(
        f"{base}/v1/events", {"action": "block", "tool": "Bash", "team": "sec"}, token="test-token",
    )
    assert status == 429
    assert json.loads(body)["error"] == "rate limited"


# ── team dashboard: batched events, summary, isolation ──────────────────────

def _batch(user: str, *events: tuple[str, str]) -> dict:
    return {"events": [
        {"event": ev, "tool": tool, "user": user, "session": f"s-{user}", "cli": "claude",
         "hook": "pre_tool_use", "categories": ["openai_key"] if ev == "redact" else [],
         "count": 1 if ev == "redact" else 0, "mode": "observe"}
        for ev, tool in events
    ]}


def test_batched_events_feed_summary(running_server):
    base, _ = running_server
    status, body = _post(
        f"{base}/v1/events",
        _batch("alice", ("tool_call", "Bash"), ("tool_call", "Read"), ("would_block", "Read"), ("redact", "Bash")),
        token="test-token",
    )
    assert status == 200 and json.loads(body)["accepted"] == 4
    _post(f"{base}/v1/events", _batch("bob", ("tool_call", "Bash")), token="test-token")

    status, body = _get(f"{base}/v1/summary", token="test-token")
    assert status == 200
    summary = json.loads(body)
    assert summary["totals"]["developers"] == 2
    assert summary["totals"]["tool_calls"] == 3
    assert summary["totals"]["would_block"] == 1
    assert summary["totals"]["secrets_redacted"] == 1
    alice = next(d for d in summary["developers"] if d["user"] == "alice")
    assert alice["tool_calls"] == 2 and alice["would_block"] == 1
    assert summary["tools"][0] == {"tool": "Bash", "calls": 2}


def test_recent_events_filter_by_user(running_server):
    base, _ = running_server
    _post(f"{base}/v1/events", _batch("alice", ("tool_call", "Bash")), token="test-token")
    _post(f"{base}/v1/events", _batch("bob", ("would_block", "Read")), token="test-token")
    status, body = _get(f"{base}/v1/events?user=bob", token="test-token")
    assert status == 200
    events = json.loads(body)["events"]
    assert [e["user"] for e in events] == ["bob"]
    assert "tenant" not in events[0]


def test_read_endpoints_require_token(running_server):
    base, _ = running_server
    assert _get(f"{base}/v1/events")[0] == 401
    assert _get(f"{base}/v1/summary", token="wrong")[0] == 401


def test_dashboard_page_is_served(running_server):
    base, _ = running_server
    status, body = _get(f"{base}/")
    assert status == 200
    assert b"privacyhook team dashboard" in body


def test_missing_policy_file_serves_empty_rules(running_server):
    base, policy_path = running_server
    policy_path.unlink()
    status, body = _get(f"{base}/v1/policy", token="test-token")
    assert status == 200
    assert json.loads(body)["rules"] == []


def test_rejects_non_list_events(running_server):
    base, _ = running_server
    status, _ = _post(f"{base}/v1/events", {"events": "nope"}, token="test-token")
    assert status == 400


def test_multi_tenant_event_isolation(multi_tenant_server):
    base = multi_tenant_server
    _post(f"{base}/v1/events", _batch("alice", ("tool_call", "Bash")), token="token-a")
    _post(f"{base}/v1/events", _batch("mallory", ("tool_call", "Bash")), token="token-b")
    _, body_a = _get(f"{base}/v1/events", token="token-a")
    _, sum_b = _get(f"{base}/v1/summary", token="token-b")
    assert {e["user"] for e in json.loads(body_a)["events"]} == {"alice"}
    assert [d["user"] for d in json.loads(sum_b)["developers"]] == ["mallory"]
