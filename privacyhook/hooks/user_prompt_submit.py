"""UserPromptSubmit hook: scan user prompt for secrets / PII."""

from __future__ import annotations

import os
import sys
from typing import Any

from ..tokenizer import Tokenizer
from ._common import block, open_session_and_audit, read_event, write_output


def main() -> int:
    if os.environ.get("PRIVACYHOOK_DISABLED") == "1":
        return 0
    event = read_event()
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return 0
    session, audit, cli = open_session_and_audit()
    try:
        tokenizer = Tokenizer(session)
        redacted, used = tokenizer.tokenize(prompt)
        if not used:
            return 0
        categories = sorted({u.split(":")[1] for u in used})
        strict = os.environ.get("PRIVACYHOOK_STRICT") == "1"
        if strict:
            audit.append(
                hook="user_prompt_submit",
                event="block",
                tool=None,
                categories=categories,
                count=len(used),
                cli=cli,
            )
            block(
                f"prompt contains {len(used)} sensitive value(s) in categories {categories}"
            )
        audit.append(
            hook="user_prompt_submit",
            event="warn",
            tool=None,
            categories=categories,
            count=len(used),
            cli=cli,
        )
        warning = (
            f"⚠ privacyhook: {len(used)} sensitive value(s) detected in your prompt "
            f"(categories: {', '.join(categories)}). The prompt was sent unchanged, "
            f"but tokens have been recorded for `privacyhook reveal`."
        )
        write_output({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": warning,
            }
        })
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
