from __future__ import annotations

from pathlib import Path

import pytest

from controlplane.policy_yaml import PolicyYamlError, load_policy_yaml, rules_to_json


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_rules(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", """
- id: no-prod-deploy
  tool: Bash
  match_type: command_regex
  pattern: "deploy.*prod"
  action: block
  reason: "no"
""")
    rules, version = load_policy_yaml(path)
    assert len(rules) == 1
    assert rules[0].id == "no-prod-deploy"
    assert len(version) == 16


def test_hash_stable_for_same_content(tmp_path: Path):
    text = "- id: a\n  tool: Bash\n  match_type: command_regex\n  pattern: x\n  action: block\n"
    p1 = write(tmp_path / "one.yaml", text)
    p2 = write(tmp_path / "two.yaml", text)
    _, v1 = load_policy_yaml(p1)
    _, v2 = load_policy_yaml(p2)
    assert v1 == v2


def test_hash_changes_with_content(tmp_path: Path):
    p = write(tmp_path / "policy.yaml", "- id: a\n  tool: Bash\n  match_type: command_regex\n  pattern: x\n  action: block\n")
    _, v1 = load_policy_yaml(p)
    write(p, "- id: b\n  tool: Bash\n  match_type: command_regex\n  pattern: y\n  action: block\n")
    _, v2 = load_policy_yaml(p)
    assert v1 != v2


def test_non_list_top_level_rejected(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", "id: not-a-list\n")
    with pytest.raises(PolicyYamlError):
        load_policy_yaml(path)


def test_non_mapping_entry_rejected(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", "- just-a-string\n")
    with pytest.raises(PolicyYamlError):
        load_policy_yaml(path)


def test_invalid_rule_fields_rejected(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", "- id: a\n  tool: Bash\n  match_type: command_regex\n")
    with pytest.raises(PolicyYamlError):
        load_policy_yaml(path)


def test_invalid_yaml_syntax_rejected(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", "- id: a\n   tool: [unterminated\n")
    with pytest.raises(PolicyYamlError):
        load_policy_yaml(path)


def test_rules_to_json_roundtrip(tmp_path: Path):
    path = write(tmp_path / "policy.yaml", "- id: a\n  tool: Bash\n  match_type: command_regex\n  pattern: x\n  action: block\n")
    rules, _ = load_policy_yaml(path)
    as_json = rules_to_json(rules)
    assert as_json == [{"id": "a", "tool": "Bash", "match_type": "command_regex",
                         "pattern": "x", "action": "block", "reason": ""}]
