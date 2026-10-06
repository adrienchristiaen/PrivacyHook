"""Observe vs enforce mode.

privacyhook ships in **observe** mode: every check still runs and every
decision is written to the audit log, but nothing is blocked — a sensitive
read is recorded as `would_block` instead of aborting the tool call. Secret
redaction is unaffected (it never stops the agent, so it stays on in both
modes). Switch to **enforce** once the audit log shows what you want to stop.

Resolution order: `PRIVACYHOOK_MODE` env var, then the `mode` file next to the
audit log (written by `privacyhook mode <observe|enforce>`), then observe.
"""

from __future__ import annotations

import os
from pathlib import Path

from .audit import default_audit_path

OBSERVE = "observe"
ENFORCE = "enforce"
VALID_MODES = (OBSERVE, ENFORCE)
DEFAULT_MODE = OBSERVE


def mode_path() -> Path:
    return default_audit_path().parent / "mode"


def current_mode() -> str:
    env = os.environ.get("PRIVACYHOOK_MODE", "").strip().lower()
    if env in VALID_MODES:
        return env
    try:
        stored = mode_path().read_text().strip().lower()
    except OSError:
        return DEFAULT_MODE
    return stored if stored in VALID_MODES else DEFAULT_MODE


def is_enforcing() -> bool:
    return current_mode() == ENFORCE


def set_mode(mode: str) -> Path:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    p = mode_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mode + "\n")
    return p
