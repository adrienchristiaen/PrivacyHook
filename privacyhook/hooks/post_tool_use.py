"""PostToolUse hook: redact secrets in Bash/Read/WebFetch outputs."""

from __future__ import annotations

import os
import sys
from typing import Any

from ..tokenizer import Tokenizer
from . import adapters
from ._common import run, normalize_tool, open_session_and_audit, read_event, write_output

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
        replacement = adapters.render_redaction(cli, redacted)
        # Cursor and Cline let a hook read a tool result but not change it:
        # the secret still reaches the model, so record it as detected, not
        # redacted, and say so on stderr.
        audit.append(
            hook="post_tool_use",
            event="redact" if replacement else "secret_detected",
            tool=tool,
            categories=categories,
            count=len(used),
            cli=cli,
        )
        if replacement is None:
            sys.stderr.write(
                f"bodycam: {len(used)} sensitive value(s) in {tool} output "
                f"({', '.join(categories)}); {cli} does not let hooks redact tool output\n"
            )
        write_output(replacement)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(run(main))
