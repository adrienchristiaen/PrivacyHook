from __future__ import annotations

from pathlib import Path

import pytest

from controlplane.tenants import TenantConfigError, load_tenants


def test_no_config_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", raising=False)
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_TOKEN", raising=False)
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH", raising=False)
    assert load_tenants() == []


def test_legacy_single_tenant_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy = tmp_path / "policy.yaml"
    policy.write_text("[]", encoding="utf-8")
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", raising=False)
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TOKEN", "dev-token")
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH", str(policy))

    tenants = load_tenants()
    assert len(tenants) == 1
    assert tenants[0].id == "default"
    assert tenants[0].token == "dev-token"
    assert tenants[0].policy_path == policy


def test_legacy_open_mode_no_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy = tmp_path / "policy.yaml"
    policy.write_text("[]", encoding="utf-8")
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", raising=False)
    monkeypatch.delenv("HOLDTHEDOOR_CONTROLPLANE_TOKEN", raising=False)
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH", str(policy))

    tenants = load_tenants()
    assert len(tenants) == 1
    assert tenants[0].token is None


def test_multi_tenant_file_loads_all_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        "- id: acme\n  token: tok-a\n  policy_path: /a.yaml\n"
        "- id: globex\n  token: tok-b\n  policy_path: /b.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    tenants = load_tenants()
    assert [t.id for t in tenants] == ["acme", "globex"]
    assert [t.token for t in tenants] == ["tok-a", "tok-b"]


def test_multi_tenant_duplicate_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        "- id: acme\n  token: tok-a\n  policy_path: /a.yaml\n"
        "- id: acme\n  token: tok-b\n  policy_path: /b.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_duplicate_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        "- id: acme\n  token: shared-token\n  policy_path: /a.yaml\n"
        "- id: globex\n  token: shared-token\n  policy_path: /b.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_missing_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text("- id: acme\n  token: ''\n  policy_path: /a.yaml\n", encoding="utf-8")
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_missing_field_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text("- id: acme\n  token: tok-a\n", encoding="utf-8")
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_non_list_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text("id: acme\n", encoding="utf-8")
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_invalid_yaml_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text("- id: [unterminated\n", encoding="utf-8")
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tenants_path))

    with pytest.raises(TenantConfigError):
        load_tenants()


def test_multi_tenant_missing_file_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH", str(tmp_path / "nope.yaml"))
    with pytest.raises(TenantConfigError):
        load_tenants()
