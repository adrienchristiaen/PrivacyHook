from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from privacyhook.audit import AuditLog, generate_key
from privacyhook.monitor import _Handler


@pytest.fixture
def running_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRIVACYHOOK_AUDIT_DIR", str(tmp_path))
    key_path = tmp_path / "hmac.key"
    key = generate_key()
    key_path.write_bytes(key)

    log = AuditLog(path=tmp_path / "audit.jsonl", hmac_key=key)
    log.append(hook="pre_tool_use", event="block", tool="Bash", categories=[],
               count=0, reason="test block", target="rm -rf /", cli="codex")
    log.append(hook="pre_tool_use", event="allow", tool="Read", categories=[], count=0, cli="claude")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


class TestMonitorServer:
    def test_serves_html_page(self, running_server: str):
        r = urllib.request.urlopen(f"{running_server}/")
        assert r.status == 200
        assert b"privacyhook monitor" in r.read()

    def test_api_events_returns_entries(self, running_server: str):
        r = urllib.request.urlopen(f"{running_server}/api/events?last=10")
        data = json.loads(r.read())
        assert len(data) == 2
        assert data[0]["event"] == "block"
        assert data[0]["cli"] == "codex"
        assert data[1]["event"] == "allow"

    def test_api_verify_reports_intact_chain(self, running_server: str):
        r = urllib.request.urlopen(f"{running_server}/api/verify")
        assert json.loads(r.read()) == {"ok": True, "message": None}

    def test_unknown_path_404s(self, running_server: str):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{running_server}/nope")
        assert exc.value.code == 404
