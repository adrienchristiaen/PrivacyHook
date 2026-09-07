from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path

import pytest

from privacyhook.remote_policy import RemotePolicySource


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "remote_policy_cache.json"


def test_unconfigured_is_noop(cache_path: Path):
    source = RemotePolicySource(url=None, token=None, cache_path=cache_path)
    assert source.configured is False
    assert source.refresh() == []


def test_happy_path_fetches_and_caches(cache_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {
        "version": "abc123",
        "rules": [
            {"id": "r1", "tool": "Bash", "match_type": "command_regex",
             "pattern": "rm -rf", "action": "block", "reason": "no"}
        ],
    }

    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())

    source = RemotePolicySource(url="http://example.test", token="tok", cache_path=cache_path)
    rules = source.refresh()
    assert len(rules) == 1
    assert rules[0].id == "r1"
    assert cache_path.exists()


def test_network_failure_falls_back_to_cache(cache_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "version": "old",
        "fetched_at": time.time() - 1000,
        "rules": [{"id": "cached", "tool": "*", "match_type": "path_glob",
                   "pattern": "*.pem", "action": "block", "reason": ""}],
    }), encoding="utf-8")

    def boom(*a, **k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    source = RemotePolicySource(url="http://example.test", token="tok", cache_path=cache_path)
    rules = source.refresh(ttl_seconds=0)
    assert len(rules) == 1
    assert rules[0].id == "cached"


def test_no_cache_and_network_failure_returns_empty(cache_path: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    source = RemotePolicySource(url="http://example.test", token="tok", cache_path=cache_path)
    assert source.refresh(ttl_seconds=0) == []


def test_malformed_response_does_not_crash(cache_path: Path, monkeypatch: pytest.MonkeyPatch):
    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"not json"

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())

    source = RemotePolicySource(url="http://example.test", token="tok", cache_path=cache_path)
    assert source.refresh(ttl_seconds=0) == []


def test_fresh_cache_skips_network(cache_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "version": "fresh",
        "fetched_at": time.time(),
        "rules": [{"id": "cached", "tool": "*", "match_type": "path_glob",
                   "pattern": "*.pem", "action": "block", "reason": ""}],
    }), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("should not hit the network when cache is fresh")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    source = RemotePolicySource(url="http://example.test", token="tok", cache_path=cache_path)
    rules = source.refresh(ttl_seconds=30)
    assert len(rules) == 1
