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


@pytest.fixture
def running_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "- id: a\n  tool: Bash\n  match_type: command_regex\n  pattern: rm -rf\n  action: block\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH", str(policy_path))
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TOKEN", "test-token")

    cp_server._policy_cache.update(mtime=None, version="", rules_json=[])
    cp_server._decision_counts.clear()

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
    assert 'holdthedoor_policy_decisions_total{action="block",tool="Bash",team="sec"} 1' in text


def test_metrics_no_auth_required(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/metrics")
    assert status == 200


def test_unknown_path_404(running_server):
    base, _ = running_server
    status, _ = _get(f"{base}/nope")
    assert status == 404
