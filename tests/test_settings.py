from __future__ import annotations

import json
from pathlib import Path

import pytest

from privacyhook import settings as S


@pytest.fixture
def settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "settings.json"
    monkeypatch.setenv("PRIVACYHOOK_SETTINGS_PATH", str(p))
    return p


class TestInstallFresh:
    def test_creates_file_if_missing(self, settings_path: Path):
        report = S.install(yes=True)
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]
        assert "PostToolUse" in hooks
        assert "PreToolUse" in hooks
        assert "UserPromptSubmit" in hooks
        assert report["added"] == 3

    def test_dry_run_does_not_write(self, settings_path: Path):
        report = S.install(dry_run=True, yes=True)
        assert not settings_path.exists()
        assert report["dry_run"] is True
        assert report["added"] == 3

    def test_commands_use_python_module(self, settings_path: Path):
        S.install(yes=True)
        data = json.loads(settings_path.read_text())
        cmds = []
        for hook_list in data["hooks"].values():
            for entry in hook_list:
                for h in entry.get("hooks", []):
                    cmds.append(h["command"])
        assert all("privacyhook.hooks." in c for c in cmds)


class TestInstallExisting:
    def test_preserves_user_hooks(self, settings_path: Path):
        user_hook = {
            "type": "command",
            "command": "echo user-defined-hook",
            "timeout": 10,
        }
        existing = {
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Edit", "hooks": [user_hook]},
                ]
            },
            "theme": "dark",
        }
        settings_path.write_text(json.dumps(existing))
        S.install(yes=True)
        data = json.loads(settings_path.read_text())
        assert data["theme"] == "dark"
        post = data["hooks"]["PostToolUse"]
        all_hooks = [h for entry in post for h in entry.get("hooks", [])]
        assert any(h["command"] == "echo user-defined-hook" for h in all_hooks)
        assert any("privacyhook.hooks.post_tool_use" in h["command"] for h in all_hooks)

    def test_idempotent(self, settings_path: Path):
        S.install(yes=True)
        first = settings_path.read_text()
        S.install(yes=True)
        second = settings_path.read_text()
        data1 = json.loads(first)
        data2 = json.loads(second)
        assert data1 == data2

    def test_creates_backup(self, settings_path: Path):
        settings_path.write_text(json.dumps({"theme": "dark"}))
        S.install(yes=True)
        backup = settings_path.with_suffix(".json.privacyhook.bak")
        assert backup.exists()
        assert json.loads(backup.read_text()) == {"theme": "dark"}


class TestUninstall:
    def test_removes_only_our_hooks(self, settings_path: Path):
        user_hook = {"type": "command", "command": "echo me", "timeout": 5}
        settings_path.write_text(json.dumps({
            "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [user_hook]}]},
            "theme": "dark",
        }))
        S.install(yes=True)
        S.uninstall(yes=True)
        data = json.loads(settings_path.read_text())
        assert data["theme"] == "dark"
        post = data["hooks"]["PostToolUse"]
        all_hooks = [h for entry in post for h in entry.get("hooks", [])]
        assert any(h["command"] == "echo me" for h in all_hooks)
        assert not any("privacyhook" in h["command"] for h in all_hooks)

    def test_removes_empty_buckets(self, settings_path: Path):
        S.install(yes=True)
        S.uninstall(yes=True)
        data = json.loads(settings_path.read_text())
        # After uninstall on a fresh install, all buckets we added should be empty
        for bucket in ("PostToolUse", "PreToolUse", "UserPromptSubmit"):
            assert data.get("hooks", {}).get(bucket, []) == []


@pytest.fixture
def codex_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    hooks_json = tmp_path / "hooks.json"
    config_toml = tmp_path / "config.toml"
    monkeypatch.setenv("PRIVACYHOOK_CODEX_SETTINGS_PATH", str(hooks_json))
    monkeypatch.setenv("PRIVACYHOOK_CODEX_CONFIG_PATH", str(config_toml))
    return hooks_json, config_toml


class TestCodexAdapter:
    def test_hook_command_tagged_with_cli(self, codex_paths: tuple[Path, Path]):
        hooks_json, _ = codex_paths
        S.install(cli="codex", yes=True)
        data = json.loads(hooks_json.read_text())
        cmds = [
            h["command"]
            for entries in data["hooks"].values()
            for entry in entries
            for h in entry.get("hooks", [])
        ]
        assert all("--cli codex" in c for c in cmds)

    def test_install_enables_codex_hooks_feature_flag(self, codex_paths: tuple[Path, Path]):
        _, config_toml = codex_paths
        assert not config_toml.exists()
        S.install(cli="codex", yes=True)
        text = config_toml.read_text()
        assert "[features]" in text
        assert "codex_hooks = true" in text

    def test_feature_flag_preserves_existing_config(self, codex_paths: tuple[Path, Path]):
        _, config_toml = codex_paths
        config_toml.write_text("[features]\nsome_other_flag = true\n")
        S.install(cli="codex", yes=True)
        text = config_toml.read_text()
        assert "some_other_flag = true" in text
        assert "codex_hooks = true" in text

    def test_feature_flag_idempotent(self, codex_paths: tuple[Path, Path]):
        _, config_toml = codex_paths
        S.install(cli="codex", yes=True)
        first = config_toml.read_text()
        S.install(cli="codex", yes=True)
        second = config_toml.read_text()
        assert first == second
        assert second.count("codex_hooks = true") == 1

    def test_dry_run_reports_flag_needed_without_writing(self, codex_paths: tuple[Path, Path]):
        _, config_toml = codex_paths
        report = S.install(cli="codex", dry_run=True, yes=True)
        assert report["codex_feature_flag_needed"] is True
        assert not config_toml.exists()


@pytest.fixture
def opencode_plugin_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    plugin_path = tmp_path / "plugin" / "privacyhook.js"
    monkeypatch.setenv("PRIVACYHOOK_OPENCODE_PLUGIN_PATH", str(plugin_path))
    return plugin_path


class TestOpenCodeAdapter:
    def test_install_writes_plugin_file(self, opencode_plugin_path: Path):
        report = S.install(cli="opencode", yes=True)
        assert opencode_plugin_path.exists()
        text = opencode_plugin_path.read_text()
        assert "privacyhook-managed-plugin" in text
        assert "tool.execute.before" in text
        assert "tool.execute.after" in text
        assert report["added"] == 2

    def test_dry_run_does_not_write(self, opencode_plugin_path: Path):
        report = S.install(cli="opencode", dry_run=True, yes=True)
        assert not opencode_plugin_path.exists()
        assert report["dry_run"] is True

    def test_install_idempotent(self, opencode_plugin_path: Path):
        S.install(cli="opencode", yes=True)
        first = opencode_plugin_path.read_text()
        S.install(cli="opencode", yes=True)
        second = opencode_plugin_path.read_text()
        assert first == second

    def test_install_refuses_to_clobber_foreign_file(self, opencode_plugin_path: Path):
        opencode_plugin_path.parent.mkdir(parents=True, exist_ok=True)
        opencode_plugin_path.write_text("// some unrelated user plugin\nexport default {}\n")
        with pytest.raises(RuntimeError):
            S.install(cli="opencode", yes=True)

    def test_uninstall_removes_our_file(self, opencode_plugin_path: Path):
        S.install(cli="opencode", yes=True)
        report = S.uninstall(cli="opencode", yes=True)
        assert not opencode_plugin_path.exists()
        assert report["removed"] == 2

    def test_uninstall_leaves_foreign_file_alone(self, opencode_plugin_path: Path):
        opencode_plugin_path.parent.mkdir(parents=True, exist_ok=True)
        opencode_plugin_path.write_text("// some unrelated user plugin\n")
        report = S.uninstall(cli="opencode", yes=True)
        assert opencode_plugin_path.exists()
        assert report["removed"] == 0

    def test_status_reports_installed(self, opencode_plugin_path: Path):
        S.install(cli="opencode", yes=True)
        st = S.status(cli="opencode")
        assert st["installed"] is True
        assert "tool.execute.before" in st["hooks"]

    def test_status_reports_not_installed(self, opencode_plugin_path: Path):
        st = S.status(cli="opencode")
        assert st["installed"] is False
        assert st["hooks"] == []


class TestStatus:
    def test_reports_installed(self, settings_path: Path):
        S.install(yes=True)
        status = S.status()
        assert status["installed"] is True
        assert set(status["hooks"]) == {"PostToolUse", "PreToolUse", "UserPromptSubmit"}

    def test_reports_not_installed(self, settings_path: Path):
        status = S.status()
        assert status["installed"] is False
        assert status["hooks"] == []
