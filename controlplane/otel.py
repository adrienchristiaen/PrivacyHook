"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

Forward team events to an OpenTelemetry collector as OTLP/HTTP JSON logs,
so a data platform sees agent activity next to the rest of its telemetry
(Datadog, Grafana Cloud, Honeycomb, Elastic, an in-house collector, …).

Off unless an endpoint is configured:

    PRIVACYHOOK_CONTROLPLANE_OTLP_ENDPOINT=http://otel-collector:4318
    PRIVACYHOOK_CONTROLPLANE_OTLP_HEADERS=dd-api-key=xxx,other=yyy   # optional

The standard OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS are
honored as fallbacks. Stdlib only: events are queued in memory and a daemon
thread posts them in batches, so a slow collector never slows ingestion.
Batches that fail are dropped after one retry (the events are still in the
control plane's own store).
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request

_BATCH_SIZE = 500
_FLUSH_INTERVAL_SECONDS = 5.0
_QUEUE_MAX = 50_000
_TIMEOUT_SECONDS = 5.0

_SEVERITY = {  # OTel severity numbers: INFO=9, WARN=13, ERROR=17
    "block": (17, "ERROR"),
    "policy_block": (17, "ERROR"),
    "policy_tamper_detected": (17, "ERROR"),
    "would_block": (13, "WARN"),
    "would_policy_block": (13, "WARN"),
    "warn": (13, "WARN"),
    "policy_warn": (13, "WARN"),
}


def endpoint() -> str | None:
    base = (os.environ.get("PRIVACYHOOK_CONTROLPLANE_OTLP_ENDPOINT")
            or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").rstrip("/")
    if not base:
        return None
    return base if base.endswith("/v1/logs") else base + "/v1/logs"


def headers() -> dict[str, str]:
    raw = (os.environ.get("PRIVACYHOOK_CONTROLPLANE_OTLP_HEADERS")
           or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or "")
    out = {}
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, list):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    return {"key": key, "value": {"stringValue": str(value)}}


def to_log_record(tenant: str, ev: dict) -> dict:
    num, text = _SEVERITY.get(ev["event"], (9, "INFO"))
    attrs = [
        _attr("bodycam.tenant", tenant),
        _attr("bodycam.event", ev["event"]),
        _attr("bodycam.tool", ev["tool"]),
        _attr("bodycam.cli", ev["cli"]),
        _attr("bodycam.hook", ev["hook"]),
        _attr("bodycam.team", ev["team"]),
        _attr("bodycam.mode", ev["mode"]),
        _attr("enduser.id", ev["user"]),
        _attr("session.id", ev["session"]),
    ]
    if ev["rule"]:
        attrs.append(_attr("bodycam.rule", ev["rule"]))
    if ev["categories"]:
        attrs.append(_attr("bodycam.secret_categories", ev["categories"]))
        attrs.append(_attr("bodycam.secret_count", int(ev["count"])))
    return {
        "timeUnixNano": str(int(ev["ts"] * 1e9)),
        "observedTimeUnixNano": str(time.time_ns()),
        "severityNumber": num,
        "severityText": text,
        "body": {"stringValue": f"{ev['event']} {ev['tool']}"},
        "attributes": attrs,
    }


def build_payload(records: list[dict]) -> dict:
    return {"resourceLogs": [{
        "resource": {"attributes": [_attr("service.name", "bodycam-server")]},
        "scopeLogs": [{"scope": {"name": "bodycam"}, "logRecords": records}],
    }]}


class OtlpExporter:
    def __init__(self, url: str, extra_headers: dict[str, str] | None = None):
        self.url = url
        self.headers = {"Content-Type": "application/json", **(extra_headers or {})}
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self.sent = 0
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="otlp-exporter", daemon=True)
        self._thread.start()

    def submit(self, tenant: str, events: list[dict]) -> None:
        for ev in events:
            try:
                self._queue.put_nowait(to_log_record(tenant, ev))
            except queue.Full:
                self.dropped += 1

    def _post(self, records: list[dict]) -> bool:
        body = json.dumps(build_payload(records)).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def _run(self) -> None:
        while True:
            batch = [self._queue.get()]  # block until there is something to send
            deadline = time.time() + _FLUSH_INTERVAL_SECONDS
            while len(batch) < _BATCH_SIZE:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            if self._post(batch) or self._post(batch):
                self.sent += len(batch)
            else:
                self.dropped += len(batch)


_exporter: OtlpExporter | None = None
_exporter_lock = threading.Lock()


def exporter() -> OtlpExporter | None:
    """The process-wide exporter, or None when no endpoint is configured."""
    global _exporter
    url = endpoint()
    if not url:
        return None
    with _exporter_lock:
        if _exporter is None or _exporter.url != url:
            _exporter = OtlpExporter(url, headers())
        return _exporter
