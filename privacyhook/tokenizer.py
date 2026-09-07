"""Reversible session-scoped tokenization.

Replaces detected secrets/PII in text with `[WALL:<category>:<n>]` placeholders.
Same value within a session always maps to the same token (idempotent), so
re-running on already-redacted text is a no-op. `reveal(token)` returns the
original value if it exists in the session DB.
"""

from __future__ import annotations

from dataclasses import dataclass

from .patterns import categorize_match
from .session import SessionStore

_TOKEN_PREFIX = "[WALL:"
_TOKEN_SUFFIX = "]"


def _format_token(category: str, n: int) -> str:
    return f"{_TOKEN_PREFIX}{category}:{n}{_TOKEN_SUFFIX}"


@dataclass
class Tokenizer:
    session: SessionStore

    def tokenize(self, text: str) -> tuple[str, list[str]]:
        """Replace detected matches with placeholders.

        Returns (redacted_text, list_of_tokens_used_in_order). Empty list if
        nothing matched. Idempotent: re-tokenizing the redacted text yields
        no new tokens.
        """
        matches = categorize_match(text)
        if not matches:
            return text, []

        used: list[str] = []
        out: list[str] = []
        cursor = 0
        for category, original, start, end in matches:
            existing = self.session.get_token_for_original(original)
            if existing is not None:
                token = existing
            else:
                n = self.session.next_counter(category)
                token = _format_token(category, n)
                self.session.put_token(category, original, token)
            out.append(text[cursor:start])
            out.append(token)
            used.append(token)
            cursor = end
        out.append(text[cursor:])
        return "".join(out), used

    def reveal(self, token: str) -> str | None:
        return self.session.get_original(token)
