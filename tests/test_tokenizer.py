from __future__ import annotations

from pathlib import Path

import pytest

from privacyhook.session import SessionStore
from privacyhook.tokenizer import Tokenizer


@pytest.fixture
def tok(tmp_path: Path) -> Tokenizer:
    s = SessionStore.open(tmp_path / "s.db")
    return Tokenizer(s)


class TestTokenizeBasics:
    def test_no_secrets_returns_unchanged(self, tok: Tokenizer):
        text = "def hello():\n    return 42  # nothing secret here"
        redacted, used = tok.tokenize(text)
        assert redacted == text
        assert used == []

    def test_replaces_email(self, tok: Tokenizer):
        redacted, used = tok.tokenize("contact alice@example.com please")
        assert "alice@example.com" not in redacted
        assert "[WALL:email:1]" in redacted
        assert used == ["[WALL:email:1]"]

    def test_preserves_surrounding_text(self, tok: Tokenizer):
        redacted, _ = tok.tokenize("see file /etc/passwd and contact foo@bar.com")
        assert "/etc/passwd" in redacted
        assert "see file" in redacted
        assert "contact" in redacted

    def test_reveal_returns_original(self, tok: Tokenizer):
        _, used = tok.tokenize("foo@bar.com")
        assert tok.reveal(used[0]) == "foo@bar.com"

    def test_reveal_unknown_returns_none(self, tok: Tokenizer):
        assert tok.reveal("[WALL:email:999]") is None


class TestTokenizeIdempotency:
    def test_same_value_same_token_within_session(self, tok: Tokenizer):
        r1, used1 = tok.tokenize("email foo@bar.com once")
        r2, used2 = tok.tokenize("email foo@bar.com twice")
        assert used1 == used2 == ["[WALL:email:1]"]

    def test_distinct_values_get_distinct_tokens(self, tok: Tokenizer):
        _, used = tok.tokenize("a@x.com and b@y.com")
        assert used == ["[WALL:email:1]", "[WALL:email:2]"]

    def test_counter_persists_across_calls(self, tok: Tokenizer):
        tok.tokenize("a@x.com")
        _, used = tok.tokenize("b@y.com")
        assert used == ["[WALL:email:2]"]


class TestTokenizeMixedCategories:
    def test_secret_and_pii_in_same_text(self, tok: Tokenizer):
        text = "token=ghp_1234567890abcdefghijklmnopqrstuvwxyzAB email a@b.com"
        redacted, used = tok.tokenize(text)
        assert "ghp_" not in redacted
        assert "a@b.com" not in redacted
        cats = {u.split(":")[1] for u in used}
        assert "github_token" in cats
        assert "email" in cats

    def test_preserves_code_structure(self, tok: Tokenizer):
        text = "config['API_KEY'] = 'sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF'"
        redacted, used = tok.tokenize(text)
        assert "config['API_KEY']" in redacted
        assert "sk-ant-api03" not in redacted
        assert any("anthropic_key" in u for u in used)

    def test_preserves_stack_trace(self, tok: Tokenizer):
        text = '  File "/Users/foo/bar.py", line 42, in baz\n  TypeError: bad'
        redacted, used = tok.tokenize(text)
        assert redacted == text
        assert used == []


class TestTokenizerCrossSession:
    def test_new_store_starts_counter_at_one(self, tmp_path: Path):
        s1 = SessionStore.open(tmp_path / "a.db")
        s2 = SessionStore.open(tmp_path / "b.db")
        t1 = Tokenizer(s1)
        t2 = Tokenizer(s2)
        _, u1 = t1.tokenize("x@y.com")
        _, u2 = t2.tokenize("z@w.com")
        assert u1 == u2 == ["[WALL:email:1]"]

    def test_persists_across_tokenizer_instances(self, tmp_path: Path):
        path = tmp_path / "s.db"
        s = SessionStore.open(path)
        Tokenizer(s).tokenize("a@b.com")
        s.close()
        s2 = SessionStore.open(path)
        _, used = Tokenizer(s2).tokenize("a@b.com")
        assert used == ["[WALL:email:1]"]
