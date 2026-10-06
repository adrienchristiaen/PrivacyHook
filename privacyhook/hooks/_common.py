"""Shared helpers for hook entry points.

Each hook runs as `python -m privacyhook.hooks.<name>`: reads a single JSON
event from stdin, processes it, optionally writes a JSON response to stdout,
and exits with the appropriate code (0 = pass, 2 = block).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from ..audit import AuditLog, generate_key
from ..mode import is_enforcing
from ..session import SessionStore
from . import adapters


# Tool name normalization: CLI-specific names → canonical names used in logic
TOOL_ALIASES: dict[str, str] = {
    # Gemini CLI tool names
    "run_shell_command": "Bash",
    "run_code": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "replace_in_file": "Edit",
    "fetch_webpage": "WebFetch",
    "fetch_url": "WebFetch",
    # Codex CLI aliases
    "bash": "Bash",
    "read": "Read",
    "apply_patch": "Edit",
    # OpenCode aliases (bash/read shared with Codex above)
    "write": "Write",
    "edit": "Edit",
    "webfetch": "WebFetch",
    # GitHub Copilot CLI
    "view": "Read",
    "create": "Write",
    "str_replace_editor": "Edit",
    "web_fetch": "WebFetch",  # also Mistral Vibe and Cline
    # Cline
    "execute_command": "Bash",
    "write_to_file": "Write",
    # Mistral Vibe uses bash / read_file / write_file / edit (covered above)
}


def normalize_tool(name: str | None) -> str:
    if not name:
        return ""
    return TOOL_ALIASES.get(name, name)


_event_cache: dict[str, Any] | None = None


def read_event() -> dict[str, Any]:
    global _event_cache
    if _event_cache is not None:
        return _event_cache
    try:
        raw = sys.stdin.read()
    except Exception:
        _event_cache = {}
        return {}
    if not raw.strip():
        _event_cache = {}
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        _event_cache = {}
        return {}
    # Cursor, Copilot, Windsurf, Vibe and Cline each send their own shape;
    # the hooks below only ever see the Claude Code one.
    _event_cache = adapters.to_canonical(parsed, _cli_from_argv())
    sid = _event_cache.get("session_id") if isinstance(_event_cache, dict) else None
    if sid and not any(os.environ.get(v) for v, _ in _CLI_ENV_MARKERS):
        os.environ["PRIVACYHOOK_SESSION_ID"] = str(sid)
    return _event_cache


_CLI_ENV_MARKERS = [
    ("CLAUDE_SESSION_ID",  "claude"),
    ("GEMINI_SESSION_ID",  "gemini"),
    ("CODEX_SESSION_ID",   "codex"),
    ("MISTRAL_SESSION_ID", "mistral"),
]


def _cli_from_argv() -> str | None:
    """`--cli <name>` is stamped into the hook command by settings.py at
    install time (see settings._hook_command). This is the only reliable
    signal for Codex: unlike Claude Code, Codex sets no identifying env var
    at hook runtime, so without this every Codex event would misdetect as
    "unknown"."""
    argv = sys.argv[1:]
    if "--cli" in argv:
        i = argv.index("--cli")
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def detect_source_cli(event: dict[str, Any]) -> str:
    """Return which CLI triggered this hook invocation."""
    tagged = _cli_from_argv()
    if tagged:
        return tagged
    for env_var, name in _CLI_ENV_MARKERS:
        if os.environ.get(env_var):
            return name
    # Gemini / others pass session info in stdin JSON
    if event.get("session_id") or event.get("sessionId"):
        hook_event = event.get("hook_event_name", "")
        if hook_event in ("BeforeTool", "AfterTool", "BeforeAgent", "AfterAgent"):
            return "gemini"
    return "unknown"


def _resolve_session_id(event: dict[str, Any]) -> str:
    for env_var, _ in _CLI_ENV_MARKERS:
        val = os.environ.get(env_var)
        if val:
            return val
    sid = event.get("session_id") or event.get("sessionId")
    return str(sid) if sid else "default"


_wrote_output = False


def write_output(payload: dict[str, Any] | None) -> None:
    global _wrote_output
    if payload is None:
        return
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()
    _wrote_output = True


def run(main) -> int:
    """Entry point wrapper: run the hook, then give CLIs that expect an
    answer on every call (Cline) their default "allow"."""
    try:
        return main()
    finally:
        if not _wrote_output:
            write_output(adapters.default_output(_cli_from_argv()))


def _load_persistent_hmac_key() -> bytes:
    """Load (or create) the persistent HMAC key stored next to the audit log.

    Stored at ~/.local/share/privacyhook/hmac.key so it survives across
    sessions and /tmp clears — enabling cross-session chain verification.
    """
    from ..audit import default_audit_path
    key_path = default_audit_path().parent / "hmac.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        data = key_path.read_bytes()
        if len(data) == 32:
            return data
    key = generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def open_session_and_audit() -> tuple[SessionStore, AuditLog, str]:
    """Return (session, audit, source_cli)."""
    event = read_event()
    _resolve_session_id(event)
    s = SessionStore.open()
    key = _load_persistent_hmac_key()
    audit = AuditLog(hmac_key=key)
    cli = detect_source_cli(event)
    return s, audit, cli


def block(reason: str, *, prompt: bool = False) -> None:
    # Each CLI has its own refusal protocol (see adapters.render_deny):
    # Claude Code honors exit 2 + stderr, Codex a stdout JSON decision,
    # Cursor/Copilot/Vibe/Cline a JSON answer, Windsurf exit 2.
    payload, code = adapters.render_deny(_cli_from_argv(), reason, prompt=prompt)
    write_output(payload)
    sys.stderr.write(f"privacyhook: {reason}\n")
    sys.exit(code)


def deny(audit: AuditLog, *, hook: str, event: str, message: str, **fields: Any) -> None:
    """Record a deny decision and, in enforce mode, block the tool call.

    In observe mode (the default) the decision is logged as `would_<event>`
    and the call goes through — see privacyhook/mode.py.
    """
    if is_enforcing():
        audit.append(hook=hook, event=event, **fields)
        block(message, prompt=hook == "user_prompt_submit")
    audit.append(hook=hook, event=f"would_{event}", **fields)
    sys.stderr.write(f"privacyhook (observe mode, not blocked): {message}\n")
