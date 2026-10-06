from __future__ import annotations

import pytest

from privacyhook.mode import ENFORCE, OBSERVE, current_mode, mode_path, set_mode


def test_default_is_observe(audit_dir, monkeypatch):
    monkeypatch.delenv("PRIVACYHOOK_MODE", raising=False)
    assert current_mode() == OBSERVE


def test_set_mode_persists(audit_dir, monkeypatch):
    monkeypatch.delenv("PRIVACYHOOK_MODE", raising=False)
    set_mode(ENFORCE)
    assert mode_path().read_text().strip() == "enforce"
    assert current_mode() == ENFORCE


def test_env_overrides_file(audit_dir, monkeypatch):
    set_mode(ENFORCE)
    monkeypatch.setenv("PRIVACYHOOK_MODE", "observe")
    assert current_mode() == OBSERVE


def test_invalid_values_fall_back_to_observe(audit_dir, monkeypatch):
    monkeypatch.setenv("PRIVACYHOOK_MODE", "bogus")
    mode_path().write_text("nonsense\n")
    assert current_mode() == OBSERVE


def test_set_mode_rejects_unknown(audit_dir):
    with pytest.raises(ValueError):
        set_mode("block-everything")
