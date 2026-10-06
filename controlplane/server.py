"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

privacyhook control plane: serves a centrally-managed policy.yaml to
every developer's hook, collects their event metadata, and serves the team
dashboard. Decision counters are also exposed for Grafana/Datadog.

Run:
    PRIVACYHOOK_CONTROLPLANE_POLICY_PATH=./example-policy.yaml \\
    PRIVACYHOOK_CONTROLPLANE_TOKEN=change-me \\
    python -m controlplane.server

Endpoints:
    GET  /v1/policy   — {"version": "<hash>", "rules": [...]}. Requires
                        Authorization: Bearer <token>.
    POST /v1/events   — {"events": [{event, tool, user, session, cli, …}]}
                        (batched, sent by `privacyhook join`ed hooks) or the
                        original single {"action", "tool", "team", "rule_id"}.
                        No command or path content is ever accepted here —
                        only metadata, keeping the control plane privacy-first.
    GET  /v1/events   — recent events for the caller's tenant (Bearer token).
    GET  /v1/summary  — per-developer / per-tool aggregates (Bearer token).
    GET  /            — the team dashboard (asks for the team token).
    GET  /metrics     — Prometheus text exposition of decision counters.
    GET  /healthz     — plain 200, for k8s liveness/readiness probes.

Stdlib http.server only, matching privacyhook/monitor.py's convention of no
third-party deps on the request path (PyYAML is the sole control-plane-only
dependency, isolated to policy_yaml.py).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter, defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .events_store import EventStore
from .policy_yaml import PolicyYamlError, load_policy_yaml, rules_to_json
from .tenants import Tenant, load_tenants

_counters_lock = threading.Lock()
_decision_counts: Counter[tuple[str, str, str, str]] = Counter()  # (tenant_id, action, tool, team)

_policy_cache: dict[str, dict] = {}  # tenant_id -> {mtime, version, rules_json}
_policy_cache_lock = threading.Lock()

_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_bytes()
_MAX_BODY_BYTES = 1_000_000
_MAX_EVENTS_PER_POST = 1000

_event_store: EventStore | None = None
_event_store_lock = threading.Lock()


def _store() -> EventStore:
    global _event_store
    with _event_store_lock:
        if _event_store is None:
            _event_store = EventStore()
        return _event_store


_EVENTS_RATE_WINDOW_SECONDS = 60.0
_rate_limit_lock = threading.Lock()
_rate_limit_hits: dict[str, deque] = defaultdict(deque)


def _events_rate_limit() -> int:
    # Hooks batch their events (one POST every couple of seconds per busy
    # developer), and a whole office can sit behind one NAT IP.
    return int(os.environ.get("PRIVACYHOOK_CONTROLPLANE_EVENTS_RATE_LIMIT", "600"))


def _rate_limited(client_ip: str) -> bool:
    """Sliding-window limiter: at most _events_rate_limit() POST /v1/events
    per client IP per minute. Prevents one misbehaving/spammy client from
    drowning the counters or the server."""
    now = time.time()
    with _rate_limit_lock:
        hits = _rate_limit_hits[client_ip]
        while hits and now - hits[0] > _EVENTS_RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _events_rate_limit():
            return True
        hits.append(now)
        return False


def _tenant_for_request(headers) -> Tenant | None:
    """Resolve which tenant a request belongs to. Tokens (and thus tenants)
    are static for the process lifetime, but re-read on every call — same
    cost as the old single-token env lookup, and keeps tests free to
    monkeypatch env vars per-request without a stale process-wide cache."""
    tenants = load_tenants()
    if not tenants:
        return None
    header = headers.get("Authorization", "")
    presented = header[len("Bearer ") :] if header.startswith("Bearer ") else None
    for tenant in tenants:
        if tenant.token is None or tenant.token == presented:
            return tenant
    return None


def _load_policy(tenant: Tenant) -> tuple[str, list[dict]]:
    """Re-parse the tenant's YAML file only when its mtime changes — cheap
    enough to check on every request, avoids a filesystem-watch dependency,
    and fits a ConfigMap-mounted file that changes rarely. A missing file
    means "no central rules yet" so the server runs with zero config."""
    if not tenant.policy_path.exists():
        return "empty", []
    mtime = tenant.policy_path.stat().st_mtime
    with _policy_cache_lock:
        cached = _policy_cache.get(tenant.id)
        if cached and cached["mtime"] == mtime:
            return cached["version"], cached["rules_json"]
        rules, version = load_policy_yaml(tenant.policy_path)
        rules_json = rules_to_json(rules)
        _policy_cache[tenant.id] = {"mtime": mtime, "version": version, "rules_json": rules_json}
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/healthz":
            self._send_json({"ok": True})
            return

        if parsed.path in ("/", "/dashboard"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_DASHBOARD_HTML)))
            self.end_headers()
            self.wfile.write(_DASHBOARD_HTML)
            return

        if parsed.path in ("/v1/events", "/v1/summary"):
            tenant = _tenant_for_request(self.headers)
            if tenant is None:
                self._send_json({"error": "unauthorized"}, status=401)
                return
            params = parse_qs(parsed.query)
            if parsed.path == "/v1/events":
                try:
                    limit = int(params.get("limit", ["200"])[0])
                except ValueError:
                    limit = 200
                user = params.get("user", [None])[0]
                self._send_json({"events": _store().recent(tenant.id, limit=limit, user=user)})
            else:
                try:
                    hours = float(params.get("hours", ["24"])[0])
                except ValueError:
                    hours = 24.0
                self._send_json(_store().summary(tenant.id, hours=max(0.1, min(hours, 24 * 90))))
            return

        if parsed.path == "/v1/policy":
            tenant = _tenant_for_request(self.headers)
            if tenant is None:
                self._send_json({"error": "unauthorized"}, status=401)
                return
            try:
                version, rules_json = _load_policy(tenant)
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
            "# HELP privacyhook_policy_decisions_total Policy decisions reported by hooks.",
            "# TYPE privacyhook_policy_decisions_total counter",
        ]
        with _counters_lock:
            items = list(_decision_counts.items())
        for (tenant_id, action, tool, team), count in items:
            lines.append(
                'privacyhook_policy_decisions_total{tenant="%s",action="%s",tool="%s",team="%s"} %d'
                % (tenant_id, action, tool, team, count)
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
        tenant = _tenant_for_request(self.headers)
        if tenant is None:
            self._send_json({"error": "unauthorized"}, status=401)
            return
        if _rate_limited(self.client_address[0]):
            self._send_json({"error": "rate limited"}, status=429)
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length > _MAX_BODY_BYTES:
            self._send_json({"error": "payload too large"}, status=413)
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "invalid JSON"}, status=400)
            return
        if not isinstance(payload, dict):
            self._send_json({"error": "expected a JSON object"}, status=400)
            return

        batch = payload.get("events") if "events" in payload else [payload]
        if not isinstance(batch, list):
            self._send_json({"error": "events must be a list"}, status=400)
            return
        events = [EventStore.normalize(e) for e in batch[:_MAX_EVENTS_PER_POST] if isinstance(e, dict)]
        with _counters_lock:
            for e in events:
                _decision_counts[(tenant.id, e["event"], e["tool"], e["team"])] += 1
        if events:
            _store().add(tenant.id, events)
        self._send_json({"ok": True, "accepted": len(events)})


def serve(host: str = "0.0.0.0", port: int = 8957) -> None:
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"privacyhook control plane — http://{host}:{port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve(
        host=os.environ.get("PRIVACYHOOK_CONTROLPLANE_HOST", "0.0.0.0"),
        port=int(os.environ.get("PRIVACYHOOK_CONTROLPLANE_PORT", "8957")),
    )
