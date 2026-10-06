"""Per-CLI wire formats.

The hook logic (pre_tool_use, post_tool_use, user_prompt_submit) works on
one canonical event shape, the one Claude Code sends:

    {"tool_name", "tool_input", "tool_response", "prompt", "session_id"}

Each agent tool speaks its own dialect on stdin and expects its own answer
on stdout. `to_canonical` translates the input, and the `render_*`
functions translate decisions back. The CLI is known from the `--cli`
argument that `privacyhook install` stamps into every hook command.

What each tool lets a hook do differs, and the README's support table is
derived from this file:

- rewrite a tool result (secret redaction): Claude Code, Codex, Gemini CLI,
  OpenCode, GitHub Copilot CLI, Mistral Vibe.
- only see the result (secrets are detected and recorded, not removed):
  Cursor, Cline.
- no access to tool results at all: Windsurf.
"""

from __future__ import annotations

import json
from typing import Any

# CLIs whose post-tool hook can replace the text the model sees.
REWRITES_OUTPUT = {"claude", "codex", "gemini", "opencode", "copilot", "vibe"}


def _as_dict(value: Any) -> dict:
    """Tool arguments arrive as an object or, for some CLIs, a JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _with_path(args: dict) -> dict:
    """Cline and Copilot name the file argument `path`; the hooks also read
    `path`, but keep `file_path` set so every code path sees it."""
    out = dict(args)
    if "file_path" not in out and isinstance(out.get("path"), str):
        out["file_path"] = out["path"]
    return out


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def _cursor(ev: dict) -> dict:
    name = ev.get("hook_event_name", "")
    out: dict[str, Any] = {"session_id": ev.get("conversation_id")}
    if name in ("beforeShellExecution", "afterShellExecution"):
        out["tool_name"] = "Bash"
        out["tool_input"] = {"command": ev.get("command", "")}
        if name == "afterShellExecution":
            out["tool_response"] = ev.get("output", "")
    elif name == "beforeReadFile":
        out["tool_name"] = "Read"
        out["tool_input"] = {"file_path": ev.get("file_path", "")}
    elif name == "beforeSubmitPrompt":
        out["prompt"] = ev.get("prompt", "")
    return out


def _copilot(ev: dict) -> dict:
    out: dict[str, Any] = {"session_id": ev.get("sessionId")}
    if "toolName" in ev:
        out["tool_name"] = ev.get("toolName")
        out["tool_input"] = _with_path(_as_dict(ev.get("toolArgs")))
        result = ev.get("toolResult")
        if isinstance(result, dict):
            out["tool_response"] = result.get("textResultForLlm", "")
    if "prompt" in ev:
        out["prompt"] = ev.get("prompt")
    return out


def _windsurf(ev: dict) -> dict:
    name = ev.get("agent_action_name", "")
    info = ev.get("tool_info") or {}
    out: dict[str, Any] = {"session_id": ev.get("trajectory_id")}
    if name == "pre_run_command":
        out["tool_name"] = "Bash"
        out["tool_input"] = {"command": info.get("command_line", "")}
    elif name == "pre_read_code":
        out["tool_name"] = "Read"
        out["tool_input"] = {"file_path": info.get("file_path", "")}
    elif name == "pre_write_code":
        out["tool_name"] = "Write"
        out["tool_input"] = {"file_path": info.get("file_path", "")}
    elif name == "pre_user_prompt":
        out["prompt"] = info.get("user_prompt", "")
    return out


def _vibe(ev: dict) -> dict:
    out: dict[str, Any] = {"session_id": ev.get("session_id")}
    if "tool_name" in ev:
        out["tool_name"] = ev.get("tool_name")
        out["tool_input"] = _as_dict(ev.get("tool_input"))
        if ev.get("hook_event_name") == "post_tool":
            out["tool_response"] = ev.get("tool_output_text") or ""
    return out


def _cline(ev: dict) -> dict:
    out: dict[str, Any] = {"session_id": ev.get("taskId")}
    for key in ("preToolUse", "postToolUse"):
        part = ev.get(key)
        if isinstance(part, dict):
            out["tool_name"] = part.get("toolName")
            out["tool_input"] = _with_path(_as_dict(part.get("parameters")))
            if key == "postToolUse":
                out["tool_response"] = part.get("result", "")
    prompt = ev.get("userPromptSubmit")
    if isinstance(prompt, dict):
        out["prompt"] = prompt.get("prompt", "")
    return out


_INPUT = {
    "cursor": _cursor,
    "copilot": _copilot,
    "windsurf": _windsurf,
    "vibe": _vibe,
    "cline": _cline,
}


def to_canonical(event: dict, cli: str | None) -> dict:
    """Translate a CLI's stdin payload to the Claude Code shape. Payloads
    from CLIs that already use it are returned unchanged."""
    convert = _INPUT.get(cli or "")
    if convert is None or not isinstance(event, dict):
        return event
    out = convert(event)
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def render_deny(cli: str | None, message: str, *, prompt: bool = False) -> tuple[dict | None, int]:
    """(stdout JSON, exit code) that makes `cli` refuse the tool call or prompt."""
    if cli == "cursor":
        if prompt:
            return {"continue": False, "user_message": message}, 0
        return {"permission": "deny", "user_message": message, "agent_message": message}, 0
    if cli == "copilot":
        return {"permissionDecision": "deny", "permissionDecisionReason": message}, 0
    if cli == "vibe":
        # Vibe treats a non-zero exit as a hook failure and lets the call
        # through, so the denial must be a JSON answer with exit 0.
        return {"decision": "deny", "reason": message}, 0
    if cli == "cline":
        return {"cancel": True, "errorMessage": message}, 0
    if cli == "windsurf":
        return None, 2  # stderr is shown to the user
    # Claude Code honors exit 2 + stderr; Codex reads the JSON decision.
    return {"decision": "block", "reason": message}, 2


def render_redaction(cli: str | None, redacted: str) -> dict | None:
    """stdout JSON that replaces the tool result with `redacted`, or None
    when `cli` gives hooks no way to change it."""
    if cli == "copilot":
        return {"textResultForLlm": redacted}
    if cli == "vibe":
        return {"decision": "deny", "reason": redacted}
    if cli in REWRITES_OUTPUT or cli not in _INPUT:
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": redacted}}
    return None


def render_prompt_warning(cli: str | None, warning: str) -> dict | None:
    if cli == "cursor":
        return {"continue": True, "user_message": warning}
    if cli in ("copilot", "windsurf", "vibe"):
        return None
    if cli == "cline":
        return None  # default_output() answers {"cancel": false}
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": warning}}


def default_output(cli: str | None) -> dict | None:
    """What to print when the hook has nothing to say. Cline expects a JSON
    answer from every hook; the others treat empty stdout as "allow"."""
    if cli == "cline":
        return {"cancel": False}
    return None
