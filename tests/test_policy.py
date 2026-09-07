from __future__ import annotations

import json
from pathlib import Path

import pytest

from privacyhook.policy import PolicyEngine, Rule


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    return tmp_path / "policy.json"


def test_empty_defaults_to_allow(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    action, rule = engine.evaluate("Bash", command="rm -rf /tmp/foo")
    assert action == "allow"
    assert rule is None


def test_add_and_persist(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="no-prod-deploy", tool="Bash", match_type="command_regex",
                     pattern=r"deploy.*prod", action="block", reason="prod deploy needs a human"))
    assert policy_path.exists()

    reloaded = PolicyEngine(path=policy_path)
    assert len(reloaded.list_rules()) == 1
    action, rule = reloaded.evaluate("Bash", command="./deploy.sh prod")
    assert action == "block"
    assert rule.id == "no-prod-deploy"


def test_first_match_wins(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="a", tool="Bash", match_type="command_regex", pattern="rm -rf", action="block"))
    engine.add(Rule(id="b", tool="Bash", match_type="command_regex", pattern="rm -rf", action="warn"))
    action, rule = engine.evaluate("Bash", command="rm -rf ./build")
    assert action == "block"
    assert rule.id == "a"


def test_tool_scoping(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="write-only", tool="Write", match_type="path_glob", pattern="*/secrets/*", action="block"))
    action, _ = engine.evaluate("Read", path_str="/x/secrets/y")
    assert action == "allow"
    action, _ = engine.evaluate("Write", path_str="/x/secrets/y")
    assert action == "block"


def test_wildcard_tool(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="any", tool="*", match_type="path_glob", pattern="*.pem", action="warn"))
    action, _ = engine.evaluate("Edit", path_str="cert.pem")
    assert action == "warn"


def test_path_glob_matching(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="g", tool="Read", match_type="path_glob", pattern="*/node_modules/*", action="block"))
    action, _ = engine.evaluate("Read", path_str="/repo/node_modules/pkg/index.js")
    assert action == "block"
    action, _ = engine.evaluate("Read", path_str="/repo/src/index.js")
    assert action == "allow"


def test_remove_rule(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="tmp", tool="*", match_type="command_regex", pattern="foo", action="block"))
    assert engine.remove("tmp") is True
    assert engine.remove("tmp") is False
    assert PolicyEngine(path=policy_path).list_rules() == []


def test_invalid_action_rejected():
    with pytest.raises(ValueError):
        Rule(id="x", tool="*", match_type="command_regex", pattern="foo", action="nope")


def test_invalid_match_type_rejected():
    with pytest.raises(ValueError):
        Rule(id="x", tool="*", match_type="nope", pattern="foo", action="block")


def test_corrupt_regex_does_not_crash(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="bad", tool="*", match_type="command_regex", pattern="(unclosed", action="block"))
    action, rule = engine.evaluate("Bash", command="anything")
    assert action == "allow"


def test_untampered_roundtrip_not_flagged(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="a", tool="Bash", match_type="command_regex", pattern="rm -rf", action="block"))
    reloaded = PolicyEngine(path=policy_path)
    assert reloaded.tampered is False


def test_edit_outside_api_flagged_as_tampered(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="a", tool="Bash", match_type="command_regex", pattern="rm -rf", action="block"))

    # Simulate an operator editing policy.json directly, bypassing add()/remove().
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    raw.append({"id": "sneaky", "tool": "*", "match_type": "command_regex",
                "pattern": ".*", "action": "allow"})
    policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    reloaded = PolicyEngine(path=policy_path)
    assert reloaded.tampered is True


def test_missing_signature_with_content_flagged(policy_path: Path):
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps([
        {"id": "x", "tool": "*", "match_type": "command_regex", "pattern": "foo", "action": "block"}
    ]), encoding="utf-8")
    engine = PolicyEngine(path=policy_path)
    assert engine.tampered is True


def test_add_after_tamper_resets_flag(policy_path: Path):
    engine = PolicyEngine(path=policy_path)
    engine.add(Rule(id="a", tool="Bash", match_type="command_regex", pattern="rm -rf", action="block"))
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    raw[0]["action"] = "allow"
    policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    reloaded = PolicyEngine(path=policy_path)
    assert reloaded.tampered is True
    reloaded.add(Rule(id="b", tool="*", match_type="command_regex", pattern="bar", action="warn"))
    assert reloaded.tampered is False

    verify = PolicyEngine(path=policy_path)
    assert verify.tampered is False
