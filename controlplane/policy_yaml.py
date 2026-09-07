"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

Load a security team's policy.yaml into privacyhook.policy.Rule objects.

Kept deliberately thin: this module's only job is YAML -> validated Rule
list + a content hash used as a cache-busting version string. All rule
semantics (valid actions, match types, matching logic) live in
privacyhook.policy so the control plane can never drift from what the
client actually enforces.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

import yaml

from privacyhook.policy import Rule


class PolicyYamlError(ValueError):
    pass


def load_policy_yaml(path: Path) -> tuple[list[Rule], str]:
    """Return (rules, version). Raises PolicyYamlError on invalid input."""
    raw_bytes = path.read_bytes()
    version = hashlib.sha256(raw_bytes).hexdigest()[:16]

    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8")) or []
    except yaml.YAMLError as exc:
        raise PolicyYamlError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, list):
        raise PolicyYamlError(f"{path} must contain a YAML list of rules at the top level")

    rules: list[Rule] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise PolicyYamlError(f"rule #{i} in {path} is not a mapping")
        try:
            rules.append(Rule(**entry))
        except (TypeError, ValueError) as exc:
            raise PolicyYamlError(f"rule #{i} in {path} is invalid: {exc}") from exc

    return rules, version


def rules_to_json(rules: list[Rule]) -> list[dict]:
    return [asdict(r) for r in rules]
