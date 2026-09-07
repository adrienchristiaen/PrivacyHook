"""Workspace sensitive-path scanner and tool-call gate.

Walks the workspace at startup to build a registry of sensitive files
(`.env`, SSH keys, credentials, certificates). Runtime checks (`check_path`,
`check_bash`) consult that registry plus a small set of always-block rules
to decide whether to let a tool call through.

Lifted from Iris `iris/core/security/workspace_guard.py` minus Iris-specific
config bits. Patterns sourced from `privacyhook.patterns`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import (
    SECRET_PATTERNS,
    SENSITIVE_DIRS,
    SENSITIVE_FILENAMES,
    SENSITIVE_SUFFIXES,
)

_MAX_CONTENT_SCAN_BYTES = 256 * 1024
_BLOCKED_BASH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"curl\s+[^|]*\|\s*(?:sh|bash|zsh)\b"), "curl|sh exec pattern"),
    (re.compile(r"wget\s+[^|]*\|\s*(?:sh|bash|zsh)\b"), "wget|sh exec pattern"),
    (re.compile(r"\beval\s+\$\("), "eval $(...) execution"),
]


def _basename_matches(name: str) -> bool:
    if name in SENSITIVE_FILENAMES:
        return True
    lower = name.lower()
    for prefix in (".env",):
        if lower.startswith(prefix):
            return True
    for suffix in SENSITIVE_SUFFIXES:
        if lower.endswith(suffix):
            return True
    if lower in {"credentials", "secrets", "credentials.json", "secrets.json"}:
        return True
    if lower.endswith("_secret.json") or lower.endswith(".credentials"):
        return True
    return False


@dataclass
class ScanResult:
    blocked_files: list[str] = field(default_factory=list)
    blocked_dirs: list[str] = field(default_factory=list)
    content_blocked: list[str] = field(default_factory=list)
    total_scanned: int = 0

    @property
    def total_blocked(self) -> int:
        return len(self.blocked_files) + len(self.content_blocked)


class WorkspaceGuard:
    """Workspace scanner + runtime path/bash gate."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else Path.cwd()
        self._scan: ScanResult | None = None
        self._blocked_set: set[str] = set()

    # ---- scan ---------------------------------------------------------

    def scan(self) -> ScanResult:
        result = ScanResult()
        if not self.root.exists() or not self.root.is_dir():
            self._scan = result
            return result
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SENSITIVE_DIRS]
            # Note any sensitive dirs we explicitly skipped, but with absolute paths
            here = Path(dirpath)
            for d in list(here.iterdir() if here.exists() else []):
                if d.is_dir() and d.name in SENSITIVE_DIRS:
                    result.blocked_dirs.append(str(d))
            for name in filenames:
                result.total_scanned += 1
                p = here / name
                if _basename_matches(name):
                    result.blocked_files.append(str(p))
                    continue
                # Content scan for small text files
                try:
                    if p.stat().st_size > _MAX_CONTENT_SCAN_BYTES:
                        continue
                    blob = p.read_text(encoding="utf-8", errors="ignore")
                except (OSError, UnicodeDecodeError):
                    continue
                for cat, pat in SECRET_PATTERNS.items():
                    if pat.search(blob):
                        result.content_blocked.append(str(p))
                        break
        self._scan = result
        self._blocked_set = set(result.blocked_files) | set(result.content_blocked)
        return result

    @property
    def scan_result(self) -> ScanResult | None:
        return self._scan

    # ---- runtime checks -----------------------------------------------

    def _resolve(self, path_str: str) -> Path:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        return p

    def check_path(self, path_str: str) -> tuple[bool, str]:
        """Return (blocked, reason) for a tool call targeting `path_str`."""
        if not path_str:
            return False, ""

        # 1. Filename-based always-block (catches files not in scan, e.g. /tmp/x/.env)
        name = Path(path_str).name
        if _basename_matches(name):
            return True, f"filename '{name}' is sensitive"

        # 2. Any segment is a sensitive dir
        try:
            resolved = self._resolve(path_str)
        except OSError:
            return False, ""
        for part in resolved.parts:
            if part in SENSITIVE_DIRS:
                return True, f"path is under sensitive directory '{part}'"

        # 3. In our scanned blocked set
        if str(resolved) in self._blocked_set:
            return True, "path is in workspace sensitive-paths registry"

        return False, ""

    def check_bash(self, command: str) -> tuple[bool, str]:
        """Return (blocked, reason) for a bash command."""
        if not command:
            return False, ""
        # Code-execution-from-network patterns
        for pat, reason in _BLOCKED_BASH_PATTERNS:
            if pat.search(command):
                return True, reason
        # Truncate at message-like flags: everything after -m / --message /
        # --tag / --body is a human-readable value, not a path to scan.
        stripped = re.split(r'\s(?:-m|--message|--body|--tag)\s', command, maxsplit=1)[0]
        # Also strip remaining quoted strings (with DOTALL for multiline)
        stripped = re.sub(r'"[\s\S]*?"', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r"'[\s\S]*?'", '', stripped, flags=re.DOTALL)
        # Check path-like tokens in what remains
        tokens = re.findall(r"[~./\w\-]+", stripped)
        for tok in tokens:
            if "/" in tok or tok.startswith("."):
                blocked, reason = self.check_path(tok)
                if blocked:
                    return True, reason
        return False, ""
