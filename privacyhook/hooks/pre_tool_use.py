"""PreToolUse hook: block calls targeting sensitive paths."""

from __future__ import annotations

import os
import sys
from typing import Any

from ..policy import PolicyEngine
from ..workspace import WorkspaceGuard
from ._common import block, normalize_tool, open_session_and_audit, read_event


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
                audit.append(
                    hook="pre_tool_use", event="block", tool=tool, categories=[],
                    count=0, reason=reason, target=cmd[:120], cli=cli,
                )
                block(f"bash command blocked: {reason}")
        elif path:
            blocked, reason = guard.check_path(path)
            if blocked:
                audit.append(
                    hook="pre_tool_use", event="block", tool=tool, categories=[],
                    count=0, reason=reason, target=path, cli=cli,
                )
                block(f"path {path!r} blocked: {reason}")

        target = cmd or path
        if target:
            action, rule = policy.evaluate(tool, command=cmd, path_str=path)
            if action == "block":
                audit.append(
                    hook="pre_tool_use", event="policy_block", tool=tool, categories=[],
                    count=0, reason=rule.reason or rule.pattern, target=target[:120], cli=cli,
                )
                block(f"blocked by policy rule '{rule.id}': {rule.reason or rule.pattern}")
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
