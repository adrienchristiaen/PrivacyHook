from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


FIX = Path(__file__).parent.parent / "fixtures"


def _run_hook(
    module: str, payload: dict, env: dict[str, str], cwd: Path | None = None, args: list[str] | None = None,
) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", module, *(args or [])],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        cwd=str(cwd) if cwd else None,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


@pytest.fixture
def hook_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".env").write_text("SECRET=1\n")
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("x = 1\n")
    return ({
        "CLAUDE_SESSION_ID": "hook-test",
        "PRIVACYHOOK_SESSION_ROOT": str(tmp_path / "sess"),
        "PRIVACYHOOK_AUDIT_DIR": str(tmp_path / "audit"),
        "PYTHONPATH": str(Path(__file__).parent.parent.parent),
    }, workspace)


class TestPreToolUse:
    def test_blocks_env_read(self, hook_env):
        env, ws = hook_env
        payload = json.loads((FIX / "pre_read_env.json").read_text())
        rc, out, err = _run_hook("privacyhook.hooks.pre_tool_use", payload, env, cwd=ws)
        assert rc == 2, f"expected exit 2, got {rc}: stderr={err}"
        assert ".env" in err or "sensitive" in err.lower()

    def test_allows_safe_read(self, hook_env):
        env, ws = hook_env
        payload = json.loads((FIX / "pre_read_safe.json").read_text())
        rc, _, err = _run_hook("privacyhook.hooks.pre_tool_use", payload, env, cwd=ws)
        assert rc == 0, f"unexpected block: {err}"

    def test_blocks_bash_cat_env(self, hook_env):
        env, ws = hook_env
        payload = {
            "session_id": "test",
            "tool_name": "Bash",
            "tool_input": {"command": "cat .env"},
        }
        rc, _, err = _run_hook("privacyhook.hooks.pre_tool_use", payload, env, cwd=ws)
        assert rc == 2
        assert "sensitive" in err.lower() or ".env" in err

    def test_allows_safe_bash(self, hook_env):
        env, ws = hook_env
        payload = {
            "session_id": "test",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
        rc, _, _ = _run_hook("privacyhook.hooks.pre_tool_use", payload, env, cwd=ws)
        assert rc == 0

    def test_block_also_emits_codex_style_json_decision(self, hook_env):
        # Codex CLI's documented block protocol reads a stdout JSON
        # {"decision": "block", ...} rather than relying on exit code alone.
        env, ws = hook_env
        payload = json.loads((FIX / "pre_read_env.json").read_text())
        rc, out, _ = _run_hook("privacyhook.hooks.pre_tool_use", payload, env, cwd=ws)
        assert rc == 2
        decision = json.loads(out)
        assert decision["decision"] == "block"
        assert decision["reason"]

    def test_no_control_plane_env_is_backward_compatible(self, hook_env):
        # Regression guard: with no PRIVACYHOOK_CONTROLPLANE_* vars set, the
        # hook must behave exactly as before remote policy support existed —
        # fast, no network attempt, no behavior change.
        env, ws = hook_env
        payload = {
            "session_id": "test",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
        parent_env = {k: v for k, v in os.environ.items() if not k.startswith("PRIVACYHOOK_CONTROLPLANE_")}
        proc_env = {**parent_env, **env}
        proc = subprocess.run(
            [sys.executable, "-m", "privacyhook.hooks.pre_tool_use"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=proc_env,
            cwd=str(ws),
            timeout=5,
        )
        assert proc.returncode == 0

    def test_cli_arg_tag_overrides_env_detection(self, hook_env):
        # Codex CLI sets no identifying env var at hook runtime, so the
        # `--cli` arg stamped by settings.py at install time is the only
        # reliable signal — verify it wins over CLAUDE_SESSION_ID (which is
        # also set in hook_env) end-to-end via the audit log it writes.
        env, ws = hook_env
        payload = json.loads((FIX / "pre_read_env.json").read_text())
        rc, _, _ = _run_hook(
            "privacyhook.hooks.pre_tool_use", payload, env, cwd=ws, args=["--cli", "codex"],
        )
        assert rc == 2
        audit_path = Path(env["PRIVACYHOOK_AUDIT_DIR"]) / "audit.jsonl"
        entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
        assert entries
        assert entries[-1]["cli"] == "codex"
