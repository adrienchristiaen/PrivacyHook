"""Optional centralized policy source (the "control plane").

A security team can run `controlplane/server.py` on a pod and point every
developer's hook at it via two env vars:

    HOLDTHEDOOR_CONTROLPLANE_URL=https://policy.internal.example.com
    HOLDTHEDOOR_CONTROLPLANE_TOKEN=<bearer token>

Neither is required — with both unset, `RemotePolicySource.fetch()` is a
no-op and behavior is identical to a plain local install. When set, rules
served by the control plane are treated as authoritative: they're evaluated
before local `policy.json` rules in `PolicyEngine.evaluate()`, so a
developer's local rules can never override a central block.

Network calls use stdlib `urllib` only (no new dependency on the hook path)
and are capped at a short timeout so a slow/unreachable control plane can't
stall a tool call. Any failure — timeout, DNS, non-200, malformed JSON —
falls back to the last successfully cached response rather than dropping
the security team's rules because of a network blip.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .policy import Rule

_FETCH_TIMEOUT_SECONDS = 2.0


def default_cache_path() -> Path:
    override = os.environ.get("HOLDTHEDOOR_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".local" / "share" / "holdthedoor"
    return base / "remote_policy_cache.json"


@dataclass
class RemotePolicySource:
    url: str | None = None
    token: str | None = None
    cache_path: Path | None = None

    def __post_init__(self) -> None:
        if self.url is None:
            self.url = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_URL") or None
        if self.token is None:
            self.token = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_TOKEN") or None
        if self.cache_path is None:
            self.cache_path = default_cache_path()

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def _load_cache(self) -> dict | None:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_cache(self, version: str, raw_rules: list[dict]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": version, "rules": raw_rules, "fetched_at": time.time()}
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")

    def _fetch_remote(self) -> dict | None:
        req = urllib.request.Request(
            f"{self.url.rstrip('/')}/v1/policy",
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
            return None

    def refresh(self, ttl_seconds: float = 30.0) -> list[Rule]:
        """Return the current remote rule set, network cost amortized by a
        local cache. Never raises — worst case returns the last known-good
        rules, or [] if there's never been a successful fetch."""
        if not self.configured:
            return []

        cached = self._load_cache()
        if cached and (time.time() - cached.get("fetched_at", 0)) < ttl_seconds:
            return self._rules_from_raw(cached.get("rules", []))

        fetched = self._fetch_remote()
        if fetched is not None and isinstance(fetched.get("rules"), list):
            self._save_cache(fetched.get("version", ""), fetched["rules"])
            return self._rules_from_raw(fetched["rules"])

        # Fetch failed — fail-safe: keep serving the last cached rules rather
        # than silently dropping the security team's policy.
        if cached:
            return self._rules_from_raw(cached.get("rules", []))
        return []

    @staticmethod
    def _rules_from_raw(raw_rules: list[dict]) -> list[Rule]:
        rules: list[Rule] = []
        for raw in raw_rules:
            try:
                rules.append(Rule(**raw))
            except (TypeError, ValueError):
                continue
        return rules
