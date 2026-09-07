from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "session"
    d.mkdir()
    return d


@pytest.fixture
def session_env(session_dir: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    sid = "test-session"
    monkeypatch.setenv("CLAUDE_SESSION_ID", sid)
    monkeypatch.setenv("PRIVACYHOOK_SESSION_ROOT", str(session_dir))
    return sid


@pytest.fixture
def audit_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "audit"
    d.mkdir()
    monkeypatch.setenv("PRIVACYHOOK_AUDIT_DIR", str(d))
    return d
