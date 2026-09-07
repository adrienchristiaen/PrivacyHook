from __future__ import annotations

import pytest

from privacyhook import patterns


class TestSecretPatterns:
    @pytest.mark.parametrize("text,category", [
        ("token=sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdef", "anthropic_key"),
        ("OPENAI=sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefghij", "openai_key"),
        ("ghp_1234567890abcdefghijklmnopqrstuvwxyz", "github_token"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "jwt"),
        ("contact me at alice@example.com please", "email"),
        ("server ip 10.0.0.5 internal", "private_ip"),
        ("connect to db.internal for queries", "internal_hostname"),
    ])
    def test_positive(self, text: str, category: str):
        matches = patterns.categorize_match(text)
        cats = {c for c, _, _, _ in matches}
        assert category in cats, f"expected category {category!r} in {cats!r} for {text!r}"

    @pytest.mark.parametrize("text", [
        "def hello_world():\n    return 42",
        "from foo.bar import baz",
        "commit a1b2c3d4e5f6789012345678901234567890abcd applied",
        "version 1.2.3-rc4",
        "  File \"/Users/foo/bar.py\", line 42, in baz",
        "TypeError: 'NoneType' object is not subscriptable",
        "https://example.com/path?q=1",
        "raise ValueError('expected int got str')",
    ])
    def test_negative_no_secrets(self, text: str):
        matches = patterns.categorize_match(text)
        assert matches == [], f"unexpected matches in {text!r}: {matches!r}"


class TestSensitiveNames:
    def test_filenames_contain_env(self):
        assert ".env" in patterns.SENSITIVE_FILENAMES

    def test_filenames_contain_ssh_keys(self):
        assert {"id_rsa", "id_ed25519", "id_ecdsa"} <= patterns.SENSITIVE_FILENAMES

    def test_dirs_contain_ssh(self):
        assert ".ssh" in patterns.SENSITIVE_DIRS

    def test_suffixes_contain_pem(self):
        assert {".pem", ".key"} <= patterns.SENSITIVE_SUFFIXES


class TestCategorizeMatch:
    def test_returns_position(self):
        text = "email is foo@bar.com here"
        matches = patterns.categorize_match(text)
        assert len(matches) == 1
        cat, match, start, end = matches[0]
        assert cat == "email"
        assert text[start:end] == match == "foo@bar.com"

    def test_multiple_categories(self):
        text = "key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF and email foo@bar.com"
        matches = patterns.categorize_match(text)
        cats = {c for c, _, _, _ in matches}
        assert {"anthropic_key", "email"} <= cats
