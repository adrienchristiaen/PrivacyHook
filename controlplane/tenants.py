"""Licensed under the Business Source License 1.1 — see ./LICENSE.
Free to self-host; may not be resold as a hosted/managed service.

Multi-tenant token/policy mapping for the control plane.

Most deployments are single-tenant: one security team, one token, one
policy.yaml — that's HOLDTHEDOOR_CONTROLPLANE_TOKEN +
HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH, unchanged since the MVP. A hoster
running this for several distinct clients instead points
HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH at a YAML file listing one
{id, token, policy_path} entry per client. Tokens and ids must be unique —
a leaked or malicious token from one tenant must never resolve to another
tenant's policy or metrics.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


class TenantConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Tenant:
    id: str
    token: str | None  # None means no auth required (legacy open mode)
    policy_path: Path


def _load_multi_tenant(path: Path) -> list[Tenant]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TenantConfigError(f"cannot read tenants file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw) or []
    except yaml.YAMLError as exc:
        raise TenantConfigError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, list):
        raise TenantConfigError(f"{path} must contain a YAML list of tenants at the top level")

    tenants: list[Tenant] = []
    seen_ids: set[str] = set()
    seen_tokens: set[str] = set()
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise TenantConfigError(f"tenant #{i} in {path} is not a mapping")
        try:
            tenant = Tenant(
                id=str(entry["id"]),
                token=str(entry["token"]),
                policy_path=Path(str(entry["policy_path"])),
            )
        except KeyError as exc:
            raise TenantConfigError(f"tenant #{i} in {path} is missing field {exc}") from exc

        if not tenant.token:
            raise TenantConfigError(
                f"tenant {tenant.id!r} in {path} has no token — "
                "open/no-auth mode is only supported for the legacy single-tenant config"
            )
        if tenant.id in seen_ids:
            raise TenantConfigError(f"duplicate tenant id {tenant.id!r} in {path}")
        if tenant.token in seen_tokens:
            raise TenantConfigError(f"duplicate tenant token in {path} (tenant {tenant.id!r})")
        seen_ids.add(tenant.id)
        seen_tokens.add(tenant.token)
        tenants.append(tenant)

    return tenants


def load_tenants() -> list[Tenant]:
    """Return the configured tenants: multi-tenant file if
    HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH is set, else a single legacy
    tenant from HOLDTHEDOOR_CONTROLPLANE_TOKEN/_POLICY_PATH, else []."""
    tenants_path = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH")
    if tenants_path:
        return _load_multi_tenant(Path(tenants_path))

    policy_path = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH")
    if policy_path:
        token = os.environ.get("HOLDTHEDOOR_CONTROLPLANE_TOKEN") or None
        return [Tenant(id="default", token=token, policy_path=Path(policy_path))]

    return []
