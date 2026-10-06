"""PreToolUse hook: block calls targeting sensitive paths."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from ..audit import audit_session_id
from ..policy import PolicyEngine
from ..team import record as team_record
from ..workspace import WorkspaceGuard
from ._common import deny, normalize_tool, open_session_and_audit, read_event


def _extract_path(event: dict[str, Any]) -> str | None:
    inp = event.get("tool_input") or {}
    if isinstance(inp, dict):
        for key in ("file_path", "path", "filename"):
            v = inp.get(key)
            if isinstance(v, str) and v:
                return v
    return None


def _extract_command(event: dict[str, Any]) -> str | None:
    inp = event.get("tool_input") or {}
    if isinstance(inp, dict):
        v = inp.get("command")
        if isinstance(v, str) and v:
            return v
    return None


def main() -> int:
    if os.environ.get("PRIVACYHOOK_DISABLED") == "1":
        return 0
    event = read_event()
    tool = normalize_tool(event.get("tool_name"))
    session, audit, cli = open_session_and_audit()
    # Activity metadata for the team dashboard (tool name only, no input).
    # Not written to the local audit log, which records decisions.
    team_record({"ts": time.time(), "session": audit_session_id(), "cli": cli,
                 "hook": "pre_tool_use", "event": "tool_call", "tool": tool,
                 "categories": [], "count": 0})
    try:
        guard = WorkspaceGuard()
        guard.scan()
        policy = PolicyEngine()
        if policy.tampered:
            audit.append(
                hook="pre_tool_use", event="policy_tamper_detected", tool=tool,
                categories=[], count=0,
                reason="policy.json signature missing/invalid — rules may have been edited outside privacyhook",
                target=str(policy.path), cli=cli,
            )
        cmd = _extract_command(event) if tool == "Bash" else None
        path = _extract_path(event) if tool != "Bash" else None

        if cmd:
            blocked, reason = guard.check_bash(cmd)
            if blocked:
                deny(
                    audit, hook="pre_tool_use", event="block",
                    message=f"bash command blocked: {reason}",
                    tool=tool, categories=[], count=0, reason=reason, target=cmd[:120], cli=cli,
                )
        elif path:
            blocked, reason = guard.check_path(path)
            if blocked:
                deny(
                    audit, hook="pre_tool_use", event="block",
                    message=f"path {path!r} blocked: {reason}",
                    tool=tool, categories=[], count=0, reason=reason, target=path, cli=cli,
                )

        target = cmd or path
        if target:
            action, rule = policy.evaluate(tool, command=cmd, path_str=path)
            if action == "block":
                deny(
                    audit, hook="pre_tool_use", event="policy_block",
                    message=f"blocked by policy rule '{rule.id}': {rule.reason or rule.pattern}",
                    tool=tool, categories=[], count=0, reason=rule.reason or rule.pattern,
                    target=target[:120], cli=cli,
                )
            elif action == "warn":
                audit.append(
                    hook="pre_tool_use", event="policy_warn", tool=tool, categories=[],
                    count=0, reason=rule.reason or rule.pattern, target=target[:120], cli=cli,
                )
                sys.stderr.write(f"privacyhook: policy warning ({rule.id}): {rule.reason or rule.pattern}\n")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
