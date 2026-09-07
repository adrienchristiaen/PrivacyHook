"""PostToolUse hook: redact secrets in Bash/Read/WebFetch outputs."""

from __future__ import annotations

import os
import sys
from typing import Any

from ..tokenizer import Tokenizer
from ._common import normalize_tool, open_session_and_audit, read_event, write_output

TARGET_TOOLS = {"Bash", "Read", "WebFetch"}


def _extract_output(event: dict[str, Any]) -> str | None:
    resp = event.get("tool_response") or {}
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in ("output", "stdout", "content", "text"):
            v = resp.get(key)
            if isinstance(v, str) and v:
                return v
    return None


def main() -> int:
    if os.environ.get("PRIVACYHOOK_DISABLED") == "1":
        return 0
    event = read_event()
    tool = normalize_tool(event.get("tool_name"))
    if tool not in TARGET_TOOLS:
        return 0
    output = _extract_output(event)
    if not output:
        return 0
    session, audit, cli = open_session_and_audit()
    try:
        tokenizer = Tokenizer(session)
        redacted, used = tokenizer.tokenize(output)
        if not used:
            return 0
        categories = sorted({u.split(":")[1] for u in used})
        audit.append(
            hook="post_tool_use",
            event="redact",
            tool=tool,
            categories=categories,
            count=len(used),
            cli=cli,
        )
        write_output({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": redacted,
            }
        })
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
