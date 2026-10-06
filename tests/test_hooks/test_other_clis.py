"""End-to-end hook runs with the payloads Cursor, GitHub Copilot CLI,
Windsurf, Mistral Vibe and Cline actually send, checking that each gets its
answer in the format it understands (see privacyhook/hooks/adapters.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SECRET = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL"
PRE = "privacyhook.hooks.pre_tool_use"
POST = "privacyhook.hooks.post_tool_use"
PROMPT = "privacyhook.hooks.user_prompt_submit"


def _run(module: str, cli: str, payload: dict, env: dict[str, str], cwd: Path) -> tuple[int, dict | None, str]:
    proc = subprocess.run(
        [sys.executable, "-m", module, "--cli", cli],
        input=json.dumps(payload), capture_output=True, text=True,
        env={**os.environ, **env}, cwd=str(cwd), timeout=10,
    )
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


def _audit_events(env: dict[str, str]) -> list[dict]:
    events = []
    for f in Path(env["PRIVACYHOOK_AUDIT_DIR"]).glob("*.jsonl"):
        events += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return events


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for var in ("CLAUDE_SESSION_ID", "GEMINI_SESSION_ID", "CODEX_SESSION_ID", "MISTRAL_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
    return {
        "PRIVACYHOOK_SESSION_ROOT": str(tmp_path / "sess"),
        "PRIVACYHOOK_AUDIT_DIR": str(tmp_path / "audit"),
        "PYTHONPATH": str(Path(__file__).parent.parent.parent),
        "PRIVACYHOOK_MODE": "enforce",
    }


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (w / ".env").write_text("SECRET=1\n")
    (w / "app.py").write_text("x = 1\n")
    return w


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

def _cursor(event: str, **fields) -> dict:
    return {"conversation_id": "conv-123", "generation_id": "gen-1", "model": "claude-4",
            "hook_event_name": event, "cursor_version": "2.1.0", "workspace_roots": ["/ws"],
            "user_email": None, "transcript_path": None, **fields}


class TestCursor:
    def test_denies_env_read(self, env, ws):
        rc, out, _ = _run(PRE, "cursor", _cursor("beforeReadFile", file_path=str(ws / ".env"),
                                                 content="SECRET=1\n", attachments=[]), env, ws)
        assert rc == 0
        assert out["permission"] == "deny" and ".env" in out["user_message"]

    def test_allows_safe_shell(self, env, ws):
        rc, out, _ = _run(PRE, "cursor", _cursor("beforeShellExecution", command="ls -la",
                                                 cwd=str(ws), sandbox=False), env, ws)
        assert rc == 0 and out is None

    def test_observe_mode_allows_and_records(self, env, ws):
        env = {**env, "PRIVACYHOOK_MODE": "observe"}
        rc, out, _ = _run(PRE, "cursor", _cursor("beforeReadFile", file_path=str(ws / ".env"),
                                                 content="", attachments=[]), env, ws)
        assert rc == 0 and out is None
        assert any(e["event"] == "would_block" and e.get("cli") == "cursor" for e in _audit_events(env))

    def test_secret_in_shell_output_is_detected_not_redacted(self, env, ws):
        rc, out, err = _run(POST, "cursor", _cursor("afterShellExecution", command="env",
                                                    output=f"OPENAI_API_KEY={SECRET}\n", duration=12,
                                                    sandbox=False), env, ws)
        assert rc == 0 and out is None
        assert "does not let hooks redact" in err
        assert any(e["event"] == "secret_detected" for e in _audit_events(env))

    def test_prompt_warning(self, env, ws):
        rc, out, _ = _run(PROMPT, "cursor", _cursor("beforeSubmitPrompt",
                                                     prompt="mail alice@example.com", attachments=[]), env, ws)
        assert rc == 0 and out["continue"] is True and "sensitive" in out["user_message"]

    def test_strict_prompt_is_stopped(self, env, ws):
        env = {**env, "PRIVACYHOOK_STRICT": "1"}
        rc, out, _ = _run(PROMPT, "cursor", _cursor("beforeSubmitPrompt",
                                                     prompt="mail alice@example.com", attachments=[]), env, ws)
        assert rc == 0 and out["continue"] is False


# ---------------------------------------------------------------------------
# GitHub Copilot CLI
# ---------------------------------------------------------------------------

def _copilot(**fields) -> dict:
    return {"sessionId": "sess-cop", "timestamp": 1760000000000, "cwd": "/ws", **fields}


class TestCopilot:
    def test_denies_env_view(self, env, ws):
        # toolArgs is a JSON-encoded string in Copilot CLI payloads.
        rc, out, _ = _run(PRE, "copilot", _copilot(toolName="view",
                                                   toolArgs=json.dumps({"path": str(ws / ".env")})), env, ws)
        assert rc == 0
        assert out["permissionDecision"] == "deny" and ".env" in out["permissionDecisionReason"]

    def test_denies_with_object_args(self, env, ws):
        rc, out, _ = _run(PRE, "copilot", _copilot(toolName="view", toolArgs={"path": str(ws / ".env")}), env, ws)
        assert out["permissionDecision"] == "deny"

    def test_allows_safe_bash(self, env, ws):
        rc, out, _ = _run(PRE, "copilot", _copilot(toolName="bash", toolArgs='{"command": "git status"}'), env, ws)
        assert rc == 0 and out is None

    def test_redacts_bash_result(self, env, ws):
        rc, out, _ = _run(POST, "copilot", _copilot(
            toolName="bash", toolArgs='{"command": "env"}',
            toolResult={"resultType": "success", "textResultForLlm": f"OPENAI_API_KEY={SECRET}\n"}), env, ws)
        assert rc == 0
        assert SECRET not in out["textResultForLlm"] and "[WALL:" in out["textResultForLlm"]

    def test_session_id_reaches_audit(self, env, ws):
        _run(PRE, "copilot", _copilot(toolName="view", toolArgs={"path": str(ws / ".env")}), env, ws)
        events = _audit_events(env)
        assert events and all(e.get("session") == "sess-cop" for e in events)


# ---------------------------------------------------------------------------
# Windsurf
# ---------------------------------------------------------------------------

def _windsurf(action: str, **tool_info) -> dict:
    return {"agent_action_name": action, "trajectory_id": "traj-1", "execution_id": "exec-1",
            "timestamp": "2026-10-06T10:00:00Z", "model_name": "SWE-1.5", "tool_info": tool_info}


class TestWindsurf:
    def test_blocks_env_read_with_exit_2(self, env, ws):
        rc, out, err = _run(PRE, "windsurf", _windsurf("pre_read_code", file_path=str(ws / ".env")), env, ws)
        assert rc == 2 and out is None and ".env" in err

    def test_allows_safe_command(self, env, ws):
        rc, out, _ = _run(PRE, "windsurf", _windsurf("pre_run_command", command_line="npm test", cwd=str(ws)), env, ws)
        assert rc == 0 and out is None

    def test_strict_prompt_blocked(self, env, ws):
        env = {**env, "PRIVACYHOOK_STRICT": "1"}
        rc, _, err = _run(PROMPT, "windsurf", _windsurf("pre_user_prompt", user_prompt="alice@example.com"), env, ws)
        assert rc == 2 and err


# ---------------------------------------------------------------------------
# Mistral Vibe
# ---------------------------------------------------------------------------

def _vibe(event: str, **fields) -> dict:
    return {"session_id": "vibe-sess", "parent_session_id": None, "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ws", "hook_event_name": event, "tool_call_id": "call_1", **fields}


class TestVibe:
    def test_denies_env_read_with_json_and_exit_0(self, env, ws):
        rc, out, _ = _run(PRE, "vibe", _vibe("pre_tool", tool_name="read_file",
                                             tool_input={"file_path": str(ws / ".env")}), env, ws)
        assert rc == 0  # a non-zero exit would make Vibe fail open
        assert out["decision"] == "deny" and ".env" in out["reason"]

    def test_redacts_tool_output_text(self, env, ws):
        rc, out, _ = _run(POST, "vibe", _vibe(
            "post_tool", tool_name="bash", tool_input={"command": "env"}, tool_status="success",
            tool_output={"stdout": f"KEY={SECRET}"}, tool_output_text=f"KEY={SECRET}\n",
            tool_error=None, duration_ms=8), env, ws)
        assert rc == 0 and out["decision"] == "deny"
        assert SECRET not in out["reason"] and "[WALL:" in out["reason"]


# ---------------------------------------------------------------------------
# Cline
# ---------------------------------------------------------------------------

def _cline(**fields) -> dict:
    return {"taskId": "task-9", "clineVersion": "3.40.0", "timestamp": "1760000000000",
            "workspaceRoots": ["/ws"], "userId": "u1", **fields}


class TestCline:
    def test_cancels_env_read(self, env, ws):
        rc, out, _ = _run(PRE, "cline", _cline(preToolUse={"toolName": "read_file",
                                                           "parameters": {"path": str(ws / ".env")}}), env, ws)
        assert rc == 0 and out["cancel"] is True and ".env" in out["errorMessage"]

    def test_always_answers_json_when_allowing(self, env, ws):
        rc, out, _ = _run(PRE, "cline", _cline(preToolUse={"toolName": "execute_command",
                                                           "parameters": {"command": "ls"}}), env, ws)
        assert rc == 0 and out == {"cancel": False}

    def test_secret_in_result_is_detected(self, env, ws):
        rc, out, err = _run(POST, "cline", _cline(postToolUse={
            "toolName": "execute_command", "parameters": {"command": "env"},
            "result": f"KEY={SECRET}", "success": True, "executionTimeMs": 30}), env, ws)
        assert rc == 0 and out == {"cancel": False}
        assert any(e["event"] == "secret_detected" and e.get("cli") == "cline" for e in _audit_events(env))

    def test_prompt_passes_with_default_answer(self, env, ws):
        rc, out, _ = _run(PROMPT, "cline", _cline(userPromptSubmit={"prompt": "hello", "attachments": []}), env, ws)
        assert rc == 0 and out == {"cancel": False}


def test_claude_payloads_unchanged(env, ws):
    """The existing Claude Code protocol still gets exit 2 + decision JSON."""
    rc, out, _ = _run(PRE, "claude", {"session_id": "s", "tool_name": "Read",
                                      "tool_input": {"file_path": str(ws / ".env")}}, env, ws)
    assert rc == 2 and out["decision"] == "block"
