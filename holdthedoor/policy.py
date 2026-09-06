"""User-defined tool-call policy engine.

Complements `WorkspaceGuard`'s built-in sensitive-path checks with custom
rules a user can add without touching code: block/warn on a bash command
regex or a path glob, per tool. Rules are stored as JSON at
`~/.local/share/holdthedoor/policy.json`, evaluated in file order, first
match wins. No match => allow (WorkspaceGuard's built-ins still apply
independently and cannot be weakened by a policy rule).
"""

from __future__ import annotations

import fnmatch
import hmac
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .remote_policy import RemotePolicySource

VALID_ACTIONS = {"block", "warn", "allow"}
VALID_MATCH_TYPES = {"command_regex", "path_glob"}


def default_policy_path() -> Path:
    override = os.environ.get("HOLDTHEDOOR_POLICY_PATH")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "holdthedoor" / "policy.json"


def _key_path(policy_path: Path) -> Path:
    return policy_path.parent / "policy.key"


def _sig_path(policy_path: Path) -> Path:
    return policy_path.parent / (policy_path.name + ".sig")


def _load_or_create_key(policy_path: Path) -> bytes:
    """Persistent HMAC key protecting policy.json integrity.

    Anyone who can write policy.json but not this key file (0600) cannot
    add/remove rules without the tamper flag tripping on next load.
    """
    key_path = _key_path(policy_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        data = key_path.read_bytes()
        if len(data) == 32:
            return data
    key = secrets.token_bytes(32)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def _sign(key: bytes, raw_bytes: bytes) -> str:
    return hmac.new(key, raw_bytes, sha256).hexdigest()


@dataclass
class Rule:
    id: str
    tool: str  # "*" or "Bash"/"Read"/"Write"/... ("|"-separated for several)
    match_type: str  # "command_regex" | "path_glob"
    pattern: str
    action: str  # "block" | "warn" | "allow"
    reason: str = ""

    def __post_init__(self) -> None:
        if self.match_type not in VALID_MATCH_TYPES:
            raise ValueError(f"invalid match_type {self.match_type!r}, choose from {VALID_MATCH_TYPES}")
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"invalid action {self.action!r}, choose from {VALID_ACTIONS}")

    def tools(self) -> list[str]:
        return ["*"] if self.tool == "*" else [t.strip() for t in self.tool.split("|")]

    def applies_to(self, tool: str) -> bool:
        ts = self.tools()
        return "*" in ts or tool in ts

    def matches(self, target: str) -> bool:
        if self.match_type == "command_regex":
            try:
                return re.search(self.pattern, target) is not None
            except re.error:
                return False
        return fnmatch.fnmatch(target, self.pattern)


def _load_raw(path: Path) -> tuple[list[dict], bool]:
    """Return (rules, tampered). tampered=True if a signature exists and
    doesn't match, or rules exist with no signature at all (e.g. an editor
    bypassing the API). An engine that has never called add()/remove() and
    finds a bare empty/missing file is not considered tampered."""
    if not path.exists():
        return [], False
    raw_bytes = path.read_bytes()
    try:
        data = json.loads(raw_bytes.decode("utf-8") or "[]")
    except json.JSONDecodeError:
        return [], False
    rules = data if isinstance(data, list) else []

    sig_path = _sig_path(path)
    key = _load_or_create_key(path)
    expected = _sign(key, raw_bytes)
    if sig_path.exists():
        stored = sig_path.read_text(encoding="utf-8").strip()
        if not hmac.compare_digest(stored, expected):
            return rules, True
        return rules, False
    # No signature file: tampered only if there's actually content to protect.
    return rules, bool(rules)


def _save_raw(path: Path, rules: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = json.dumps(rules, indent=2).encode("utf-8")
    path.write_bytes(raw_bytes)
    key = _load_or_create_key(path)
    _sig_path(path).write_text(_sign(key, raw_bytes), encoding="utf-8")


class PolicyEngine:
    """Loads and evaluates user-defined rules against tool-call events."""

    def __init__(self, path: Path | None = None, remote: "RemotePolicySource | None" = None):
        self.path = path or default_policy_path()
        raw, self.tampered = _load_raw(self.path)
        self.rules: list[Rule] = [Rule(**r) for r in raw]
        if remote is None:
            from .remote_policy import RemotePolicySource
            remote = RemotePolicySource()
        self.remote = remote

    def evaluate(
        self, tool: str, *, command: str | None = None, path_str: str | None = None
    ) -> tuple[str, Rule | None]:
        """Return (action, rule): action is 'block', 'warn', or 'allow'.

        Remote (control-plane) rules are checked before local ones — a
        security team's centrally-managed policy is authoritative and can't
        be overridden by a developer's local policy.json.
        """
        for rule in [*self.remote.refresh(), *self.rules]:
            if not rule.applies_to(tool):
                continue
            target = command if rule.match_type == "command_regex" else path_str
            if not target:
                continue
            if rule.matches(target):
                return rule.action, rule
        return "allow", None

    def add(self, rule: Rule) -> None:
        raw, _ = _load_raw(self.path)
        raw.append(asdict(rule))
        _save_raw(self.path, raw)
        self.rules.append(rule)
        self.tampered = False

    def remove(self, rule_id: str) -> bool:
        raw, _ = _load_raw(self.path)
        new_raw = [r for r in raw if r.get("id") != rule_id]
        removed = len(new_raw) != len(raw)
        if removed:
            _save_raw(self.path, new_raw)
            self.rules = [Rule(**r) for r in new_raw]
            self.tampered = False
        return removed

    def list_rules(self) -> list[Rule]:
        return list(self.rules)
