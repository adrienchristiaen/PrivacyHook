"""Bodycam is the new name of PrivacyHook: old and new spellings both work."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run(code: str, env: dict[str, str]) -> str:
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT), **env}, timeout=10)
    return out.stdout.strip()


def test_bodycam_env_vars_are_aliases(tmp_path):
    code = "from privacyhook.mode import current_mode; print(current_mode())"
    assert _run(code, {"BODYCAM_MODE": "enforce", "PRIVACYHOOK_AUDIT_DIR": str(tmp_path)}) == "enforce"


def test_old_env_var_wins_when_both_are_set(tmp_path):
    code = "from privacyhook.mode import current_mode; print(current_mode())"
    env = {"BODYCAM_MODE": "enforce", "PRIVACYHOOK_MODE": "observe", "PRIVACYHOOK_AUDIT_DIR": str(tmp_path)}
    assert _run(code, env) == "observe"


def test_server_env_aliases():
    code = "import controlplane, os; print(os.environ['PRIVACYHOOK_CONTROLPLANE_TOKEN'])"
    assert _run(code, {"BODYCAM_SERVER_TOKEN": "t0k"}) == "t0k"


def test_cli_is_named_bodycam():
    out = subprocess.run([sys.executable, "-m", "privacyhook.cli", "--help"], capture_output=True,
                         text=True, env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=10)
    assert out.stdout.startswith("usage: bodycam")
