"""Local-only monitoring UI: stdlib HTTP server serving a live audit-log view.

No third-party deps. Binds to 127.0.0.1 by default — never exposes the audit
log beyond the local machine unless the user explicitly passes --host.

Endpoints:
  GET /              — HTML page (table + filters, vanilla JS)
  GET /api/events    — JSON array of recent entries (?last=N, default 200)
  GET /api/verify    — HMAC chain verification result
  GET /api/stream    — Server-Sent Events: pushes new entries as they land
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .audit import AuditLog


def _open_log() -> AuditLog:
    from .hooks._common import _load_persistent_hmac_key
    return AuditLog(hmac_key=_load_persistent_hmac_key())


_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>privacyhook monitor</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 13px/1.4 ui-monospace, monospace; margin: 0; padding: 1.5rem;
         background: #0d1117; color: #c9d1d9; }
  @media (prefers-color-scheme: light) {
    body { background: #fff; color: #24292f; }
    th { border-bottom-color: #d0d7de !important; }
    td { border-bottom-color: #eee !important; }
    .pill { background: #eee !important; }
  }
  h1 { font-size: 1rem; margin: 0 0 .25rem; }
  .sub { opacity: .6; margin-bottom: 1rem; }
  .bar { display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap; align-items: center; }
  select, input { background: transparent; color: inherit; border: 1px solid #444; border-radius: 4px;
                  padding: .3rem .5rem; font: inherit; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #222; white-space: nowrap; }
  td.reason { white-space: normal; }
  th { opacity: .6; font-weight: 600; font-size: .75rem; text-transform: uppercase; }
  .pill { display: inline-block; padding: .1rem .5rem; border-radius: 10px; background: #222; font-size: .75rem; }
  .block, .policy_block { color: #f85149; }
  .warn, .policy_warn { color: #d29922; }
  .redact { color: #58a6ff; }
  .allow { color: #3fb950; }
  .policy_tamper_detected { color: #f0883e; font-weight: bold; }
  #chain { font-size: .85rem; }
  #chain.ok { color: #3fb950; }
  #chain.bad { color: #f85149; }
</style>
</head>
<body>
  <h1>privacyhook monitor</h1>
  <div class="sub">live audit log — local only</div>
  <div class="bar">
    <input id="q" placeholder="filter (tool, reason, session...)" size="28">
    <select id="ev">
      <option value="">all events</option>
      <option value="block">block</option>
      <option value="policy_block">policy_block</option>
      <option value="warn">warn</option>
      <option value="policy_warn">policy_warn</option>
      <option value="redact">redact</option>
      <option value="allow">allow</option>
      <option value="policy_tamper_detected">policy_tamper_detected</option>
    </select>
    <span id="chain">checking chain…</span>
    <span style="flex:1"></span>
    <span id="count" class="pill">0 events</span>
  </div>
  <table>
    <thead><tr><th>time</th><th>cli</th><th>session</th><th>hook</th><th>event</th><th>tool</th><th>reason / target</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>

<script>
let all = [];

function fmtTs(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function render() {
  const q = document.getElementById('q').value.toLowerCase();
  const ev = document.getElementById('ev').value;
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  let shown = 0;
  for (const e of all) {
    if (ev && e.event !== ev) continue;
    const hay = `${e.tool||''} ${e.reason||''} ${e.target||''} ${e.session||''} ${e.cli||''}`.toLowerCase();
    if (q && !hay.includes(q)) continue;
    shown++;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${fmtTs(e.ts)}</td><td>${e.cli||'—'}</td><td>${(e.session||'').slice(0,8)}</td>` +
      `<td>${e.hook||''}</td><td class="${e.event}">${e.event||''}</td><td>${e.tool||'—'}</td>` +
      `<td class="reason">${(e.reason||'')} ${e.target?('<span style="opacity:.5">'+e.target+'</span>'):''}</td>`;
    rows.prepend(tr);
  }
  document.getElementById('count').textContent = `${shown} / ${all.length} events`;
}

document.getElementById('q').addEventListener('input', render);
document.getElementById('ev').addEventListener('change', render);

fetch('/api/events?last=500').then(r => r.json()).then(data => { all = data; render(); });
fetch('/api/verify').then(r => r.json()).then(v => {
  const el = document.getElementById('chain');
  el.textContent = v.ok ? 'chain intact' : ('chain BROKEN: ' + v.message);
  el.className = v.ok ? 'ok' : 'bad';
});

const es = new EventSource('/api/stream');
es.onmessage = (msg) => {
  all.push(JSON.parse(msg.data));
  render();
};
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # silence default stderr access log
        pass

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = _PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/events":
            qs = parse_qs(parsed.query)
            last = int(qs.get("last", ["200"])[0])
            log = _open_log()
            self._send_json(log.read_last(last) if last else log.read_all())
            return

        if parsed.path == "/api/verify":
            log = _open_log()
            ok, msg = log.verify()
            self._send_json({"ok": ok, "message": msg})
            return

        if parsed.path == "/api/stream":
            self._stream_sse()
            return

        self.send_response(404)
        self.end_headers()

    def _stream_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        log = _open_log()
        seen = len(log.read_all())
        try:
            while True:
                entries = log.read_all()
                for e in entries[seen:]:
                    chunk = f"data: {json.dumps(e)}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                self.wfile.flush()
                seen = len(entries)
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return


def serve(host: str = "127.0.0.1", port: int = 8956, *, open_browser: bool = False) -> None:
    server = None
    tried = []
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer((host, candidate), _Handler)
            port = candidate
            break
        except OSError as exc:
            tried.append(candidate)
            if exc.errno != 48:  # not "address already in use" — surface it
                raise
    if server is None:
        raise SystemExit(
            f"privacyhook: ports {tried[0]}-{tried[-1]} all in use. "
            f"Pass --port to pick one explicitly."
        )
    url = f"http://{host}:{port}/"
    print(f"privacyhook monitor  —  {url}  (Ctrl-C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
