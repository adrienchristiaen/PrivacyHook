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


class TestUserPromptSubmit:
    def test_warns_on_pii_in_prompt(self, hook_env):
        payload = json.loads((FIX / "prompt_with_pii.json").read_text())
        rc, out, err = _run_hook("privacyhook.hooks.user_prompt_submit", payload, hook_env)
        assert rc == 0, f"stderr: {err}"
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "email" in ctx.lower() or "[WALL:" in ctx

    def test_passthrough_clean_prompt(self, hook_env):
        payload = json.loads((FIX / "prompt_clean.json").read_text())
        rc, out, _ = _run_hook("privacyhook.hooks.user_prompt_submit", payload, hook_env)
        assert rc == 0
        # No additionalContext when nothing matched
        if out.strip():
            result = json.loads(out)
            assert not result.get("hookSpecificOutput", {}).get("additionalContext")

    def test_strict_mode_blocks(self, hook_env):
        payload = json.loads((FIX / "prompt_with_pii.json").read_text())
        env = {**hook_env, "PRIVACYHOOK_STRICT": "1"}
        rc, _, err = _run_hook("privacyhook.hooks.user_prompt_submit", payload, env)
        assert rc == 2
        assert err
