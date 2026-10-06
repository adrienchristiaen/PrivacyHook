"""Team sync: ship event metadata to a shared control plane.

A developer joins once with `privacyhook join <url> --token <token>`; from
then on every hook event (tool call, redaction, block, would_block, …) is
mirrored to the team's control plane, which serves the team dashboard.

Only metadata leaves the machine: event type, tool name, CLI, session id,
developer name, secret *categories* and counts, and the policy rule reason
for policy matches. Never a command, a path, a prompt, or a secret value.

Hooks must stay fast and must never fail because the network is down, so
`record()` only appends to a local outbox and starts a detached flusher
process. The flusher batches whatever is queued, POSTs it, and puts it back
in the outbox if the server is unreachable.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .audit import default_audit_path

_POST_TIMEOUT_SECONDS = 3.0
_BATCH_DELAY_SECONDS = 2.0  # flusher waits so bursts of tool calls go out as one request
_LOCK_STALE_SECONDS = 30.0
_OUTBOX_MAX_LINES = 5000

# Fields that may leave the machine. Anything else (target, raw reason,
# hmac chain) stays in the local audit log only.
_SAFE_FIELDS = ("ts", "session", "cli", "hook", "event", "tool", "categories", "count")


def _base_dir() -> Path:
    return default_audit_path().parent


def config_path() -> Path:
    return _base_dir() / "team.json"


def outbox_path() -> Path:
    return _base_dir() / "team_outbox.jsonl"


def _lock_path() -> Path:
    return _base_dir() / "team_outbox.lock"


def default_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def load_config() -> dict | None:
    """Return {"url", "token", "user"} or None when not in a team.

    PRIVACYHOOK_CONTROLPLANE_URL / _TOKEN still work (CI, managed laptops)
    and take precedence over the file written by `privacyhook join`.
    """
    env_url = os.environ.get("PRIVACYHOOK_CONTROLPLANE_URL")
    stored: dict = {}
    try:
        stored = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    url = env_url or stored.get("url")
    if not url:
        return None
    return {
        "url": url.rstrip("/"),
        "token": os.environ.get("PRIVACYHOOK_CONTROLPLANE_TOKEN") or stored.get("token"),
        "user": os.environ.get("PRIVACYHOOK_USER") or stored.get("user") or default_user(),
    }


def save_config(url: str, token: str | None, user: str) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"url": url.rstrip("/"), "token": token, "user": user}, indent=2))
    try:
        p.chmod(0o600)  # holds a bearer token
    except OSError:
        pass
    return p


def clear_config() -> bool:
    removed = False
    for p in (config_path(), outbox_path()):
        try:
            p.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def _request(url: str, token: str | None, *, data: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=_POST_TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, b""


def check_connection(url: str, token: str | None) -> tuple[bool, str]:
    status, _ = _request(f"{url.rstrip('/')}/v1/policy", token)
    if status == 200:
        return True, "connected"
    if status == 401:
        return False, "the server rejected this token"
    if status == 0:
        return False, "server unreachable"
    return False, f"unexpected HTTP {status}"


def sanitize(payload: dict, *, user: str) -> dict:
    out = {k: payload[k] for k in _SAFE_FIELDS if k in payload}
    out["user"] = user
    # Policy rule reasons are written by the team's admins, not taken from the
    # agent's input, so they are safe to share; built-in reasons quote paths.
    if str(payload.get("event", "")).endswith("policy_block") or payload.get("event") == "policy_warn":
        if payload.get("reason"):
            out["rule"] = str(payload["reason"])[:200]
    try:
        from .mode import current_mode
        out["mode"] = current_mode()
    except Exception:
        pass
    return out


def record(payload: dict) -> None:
    """Queue one event for the team control plane. Never raises."""
    try:
        cfg = load_config()
        if cfg is None:
            return
        event = sanitize(payload, user=cfg["user"])
        p = outbox_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        if os.environ.get("PRIVACYHOOK_TEAM_SYNC") == "1":
            flush(delay=0)
        else:
            _spawn_flusher()
    except Exception:
        pass


def _lock_is_held() -> bool:
    try:
        age = time.time() - _lock_path().stat().st_mtime
    except FileNotFoundError:
        return False
    return age < _LOCK_STALE_SECONDS


def _spawn_flusher() -> None:
    if _lock_is_held():
        return  # a flusher is already waiting; it will pick this event up
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "privacyhook.team", "flush"], **kwargs)


def _acquire_lock() -> bool:
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and not _lock_is_held():
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def _requeue(lines: list[str]) -> None:
    p = outbox_path()
    existing = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    merged = [*lines, *existing][-_OUTBOX_MAX_LINES:]
    p.write_text("".join(line + "\n" for line in merged), encoding="utf-8")


def flush(delay: float = _BATCH_DELAY_SECONDS) -> int:
    """Send everything in the outbox. Returns the number of events sent."""
    cfg = load_config()
    if cfg is None or not _acquire_lock():
        return 0
    try:
        if delay:
            time.sleep(delay)
        p = outbox_path()
        sending = p.with_suffix(".sending")
        try:
            os.replace(p, sending)
        except FileNotFoundError:
            return 0
        lines = [line for line in sending.read_text(encoding="utf-8").splitlines() if line.strip()]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not events:
            sending.unlink(missing_ok=True)
            return 0
        body = json.dumps({"events": events}).encode("utf-8")
        status, _ = _request(f"{cfg['url']}/v1/events", cfg["token"], data=body)
        if status == 200:
            sending.unlink(missing_ok=True)
            return len(events)
        _requeue(lines)
        sending.unlink(missing_ok=True)
        return 0
    finally:
        _lock_path().unlink(missing_ok=True)


def pending_count() -> int:
    try:
        return sum(1 for line in outbox_path().read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["flush"]:
        flush()
