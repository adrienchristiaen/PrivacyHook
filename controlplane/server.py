"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

holdthedoor control plane: serves a centrally-managed policy.yaml to
every developer's hook, and exposes decision counters for Grafana/Datadog.

Run:
    HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH=./example-policy.yaml \\
    HOLDTHEDOOR_CONTROLPLANE_TOKEN=change-me \\
    python -m controlplane.server

Endpoints:
    GET  /v1/policy   — {"version": "<hash>", "rules": [...]}. Requires
                        Authorization: Bearer <token>.
    POST /v1/events   — {"action", "tool", "team", "rule_id"}. No command or
                        path content is ever accepted here — only decision
                        metadata, keeping the control plane privacy-first.
    GET  /metrics     — Prometheus text exposition of decision counters.
    GET  /healthz     — plain 200, for k8s liveness/readiness probes.

Stdlib http.server only, matching holdthedoor/monitor.py's convention of no
third-party deps on the request path (PyYAML is the sole control-plane-only
dependency, isolated to policy_yaml.py).
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .policy_yaml import PolicyYamlError, load_policy_yaml, rules_to_json

_counters_lock = threading.Lock()
_decision_counts: Counter[tuple[str, str, str]] = Counter()  # (action, tool, team)

_policy_cache: dict = {"mtime": None, "version": "", "rules_json": []}
_policy_cache_lock = threading.Lock()


def _policy_path() -> Path:
    override = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH")
    if not override:
        raise RuntimeError("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH must be set")
    return Path(override)


def _expected_token() -> str | None:
    return os.environ.get("HOLDTHEDOOR_CONTROLPLANE_TOKEN") or None


def _load_policy() -> tuple[str, list[dict]]:
    """Re-parse the YAML file only when its mtime changes — cheap enough to
    check on every request, avoids a filesystem-watch dependency, and fits
    a ConfigMap-mounted file that changes rarely."""
    path = _policy_path()
    mtime = path.stat().st_mtime
    with _policy_cache_lock:
        if _policy_cache["mtime"] == mtime:
            return _policy_cache["version"], _policy_cache["rules_json"]
        rules, version = load_policy_yaml(path)
        rules_json = rules_to_json(rules)
        _policy_cache.update(mtime=mtime, version=version, rules_json=rules_json)
        return version, rules_json


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib override
        pass

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _expected_token()
        if not expected:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {expected}"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/healthz":
            self._send_json({"ok": True})
            return

        if parsed.path == "/v1/policy":
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=401)
                return
            try:
                version, rules_json = _load_policy()
            except (PolicyYamlError, OSError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"version": version, "rules": rules_json})
            return

        if parsed.path == "/metrics":
            self._send_metrics()
            return

        self.send_response(404)
        self.end_headers()

    def _send_metrics(self) -> None:
        lines = [
            "# HELP holdthedoor_policy_decisions_total Policy decisions reported by hooks.",
            "# TYPE holdthedoor_policy_decisions_total counter",
        ]
        with _counters_lock:
            items = list(_decision_counts.items())
        for (action, tool, team), count in items:
            lines.append(
                'holdthedoor_policy_decisions_total{action="%s",tool="%s",team="%s"} %d'
                % (action, tool, team, count)
            )
        body = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/events":
            self.send_response(404)
            self.end_headers()
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, status=401)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, status=400)
            return

        action = str(payload.get("action", "unknown"))
        tool = str(payload.get("tool", "unknown"))
        team = str(payload.get("team", "default"))
        with _counters_lock:
            _decision_counts[(action, tool, team)] += 1
        self._send_json({"ok": True})


def serve(host: str = "0.0.0.0", port: int = 8957) -> None:
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"holdthedoor control plane — http://{host}:{port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve(
        host=os.environ.get("HOLDTHEDOOR_CONTROLPLANE_HOST", "0.0.0.0"),
        port=int(os.environ.get("HOLDTHEDOOR_CONTROLPLANE_PORT", "8957")),
    )
