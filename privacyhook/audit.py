"""HMAC-chained append-only audit log.

Each entry is a JSON line with `prev_hmac` (the previous line's hmac) and
`hmac = HMAC_SHA256(key, prev_hmac || canonical_payload)`. Tampering with
any line breaks the chain at that point, which `verify()` reports.

The HMAC key is per-session (stored in the SessionStore meta table) and is
randomly generated on first use. Even if the log file is compromised, an
attacker without the key cannot forge or repair the chain.
"""

from __future__ import annotations

import csv
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


def default_audit_path() -> Path:
    override = os.environ.get("PRIVACYHOOK_AUDIT_DIR")
    if override:
        return Path(override) / "audit.jsonl"
    return Path.home() / ".local" / "share" / "privacyhook" / "audit.jsonl"


def generate_key() -> bytes:
    return secrets.token_bytes(32)


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _compute_hmac(key: bytes, prev_hmac: str, payload: dict) -> str:
    msg = prev_hmac.encode() + _canonical(payload)
    return hmac.new(key, msg, sha256).hexdigest()


@dataclass
class AuditLog:
    """Append-only audit log with HMAC chain verification."""

    path: Path = field(default_factory=default_audit_path)
    hmac_key: bytes = field(default_factory=generate_key)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hmac(self) -> str:
        if not self.path.exists():
            return ""
        last_line = ""
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return ""
        try:
            return json.loads(last_line).get("hmac", "")
        except json.JSONDecodeError:
            return ""

    def append(
        self,
        *,
        hook: str,
        event: str,
        tool: str | None,
        categories: list[str],
        count: int,
        reason: str | None = None,
        target: str | None = None,
        cli: str | None = None,
    ) -> None:
        session_id = (os.environ.get("CLAUDE_SESSION_ID")
                      or os.environ.get("GEMINI_SESSION_ID")
                      or os.environ.get("CODEX_SESSION_ID")
                      or os.environ.get("MISTRAL_SESSION_ID")
                      or "default")
        payload: dict = {
            "ts": time.time(),
            "session": session_id[:16],
            "cli": cli or "unknown",
            "hook": hook,
            "event": event,
            "tool": tool,
            "categories": list(categories),
            "count": count,
        }
        if reason is not None:
            payload["reason"] = reason
        if target is not None:
            payload["target"] = target
        prev = self._last_hmac()
        payload["prev_hmac"] = prev
        payload["hmac"] = _compute_hmac(self.hmac_key, prev, {
            k: v for k, v in payload.items() if k != "hmac"
        })
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def read_last(self, n: int) -> list[dict]:
        all_entries = self.read_all()
        return all_entries[-n:] if n > 0 else []

    def export_csv(
        self,
        out_path: Path,
        *,
        since: float | None = None,
        until: float | None = None,
    ) -> int:
        """Write a compliance-friendly CSV export of the audit log.

        Returns the number of rows written. The first line is a `#`-prefixed
        metadata comment recording chain-verification status at export time,
        so an auditor can see integrity was checked without needing the
        (never-exported) HMAC key.
        """
        ok, verify_msg = self.verify()
        entries = self.read_all()
        if since is not None:
            entries = [e for e in entries if e.get("ts", 0) >= since]
        if until is not None:
            entries = [e for e in entries if e.get("ts", 0) <= until]

        generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = (
            f"# privacyhook audit export | "
            f"chain_verified={'true' if ok else 'false'}"
            + (f" ({verify_msg})" if verify_msg else "")
            + f" | events={len(entries)} | generated={generated}"
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            f.write(meta + "\n")
            writer = csv.writer(f)
            writer.writerow([
                "ts", "session", "cli", "hook", "event", "tool",
                "categories", "count", "reason", "target",
            ])
            for e in entries:
                ts_iso = datetime.fromtimestamp(
                    e.get("ts", 0), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                writer.writerow([
                    ts_iso,
                    e.get("session", ""),
                    e.get("cli", ""),
                    e.get("hook", ""),
                    e.get("event", ""),
                    e.get("tool", "") or "",
                    ";".join(e.get("categories", []) or []),
                    e.get("count", 0),
                    e.get("reason", "") or "",
                    e.get("target", "") or "",
                ])
        return len(entries)

    def verify(self) -> tuple[bool, str | None]:
        prev = ""
        for i, entry in enumerate(self.read_all(), start=1):
            if entry.get("prev_hmac", "") != prev:
                return False, f"chain break at line {i}: prev_hmac mismatch"
            stored = entry.get("hmac", "")
            recomputed = _compute_hmac(
                self.hmac_key, prev, {k: v for k, v in entry.items() if k != "hmac"}
            )
            if not hmac.compare_digest(stored, recomputed):
                return False, f"chain break at line {i}: hmac mismatch (tampered payload)"
            prev = stored
        return True, None
