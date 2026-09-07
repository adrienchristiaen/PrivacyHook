from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


FIX = Path(__file__).parent.parent / "fixtures"


def _run_hook(module: str, payload: dict, env: dict[str, str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", module],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


@pytest.fixture
def hook_env(tmp_path: Path) -> dict[str, str]:
    return {
        "CLAUDE_SESSION_ID": "hook-test",
        "PRIVACYHOOK_SESSION_ROOT": str(tmp_path / "sess"),
        "PRIVACYHOOK_AUDIT_DIR": str(tmp_path / "audit"),
        "PYTHONPATH": str(Path(__file__).parent.parent.parent),
    }


class TestPostToolUse:
    def test_redacts_secret_in_bash_output(self, hook_env):
        payload = json.loads((FIX / "post_bash_secret.json").read_text())
        rc, out, err = _run_hook("privacyhook.hooks.post_tool_use", payload, hook_env)
        assert rc == 0, f"stderr: {err}"
        result = json.loads(out)
        updated = result["hookSpecificOutput"]["updatedToolOutput"]
        assert "sk-proj-" not in updated
        assert "admin@example.com" not in updated
        assert "[WALL:" in updated
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    def test_passthrough_when_clean(self, hook_env):
        payload = json.loads((FIX / "post_bash_clean.json").read_text())
        rc, out, err = _run_hook("privacyhook.hooks.post_tool_use", payload, hook_env)
        assert rc == 0
        # Empty or no modification when no matches
        if out.strip():
            result = json.loads(out)
            assert "hookSpecificOutput" not in result or \
                result["hookSpecificOutput"].get("updatedToolOutput") is None

    def test_skips_non_target_tools(self, hook_env):
        payload = {
            "session_id": "test",
            "tool_name": "Edit",
            "tool_response": {"stdout": "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL"},
        }
        rc, out, _ = _run_hook("privacyhook.hooks.post_tool_use", payload, hook_env)
        assert rc == 0
        assert out.strip() == "" or "updatedToolOutput" not in out
