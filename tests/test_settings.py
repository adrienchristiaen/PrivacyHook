from __future__ import annotations

import json
import os
import sys
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


# ---------------------------------------------------------------------------
# Cursor, Copilot CLI, Windsurf (flat JSON hooks files)
# ---------------------------------------------------------------------------

_FLAT = {
    "cursor": "PRIVACYHOOK_CURSOR_HOOKS_PATH",
    "copilot": "PRIVACYHOOK_COPILOT_HOOKS_PATH",
    "windsurf": "PRIVACYHOOK_WINDSURF_HOOKS_PATH",
}


@pytest.mark.parametrize("cli", list(_FLAT))
class TestFlatJsonAdapters:
    def _path(self, cli, tmp_path, monkeypatch) -> Path:
        p = tmp_path / cli / "hooks.json"
        monkeypatch.setenv(_FLAT[cli], str(p))
        return p

    def test_install_status_uninstall(self, cli, tmp_path, monkeypatch):
        p = self._path(cli, tmp_path, monkeypatch)
        p.parent.mkdir()
        user_hook = {"command": "/usr/local/bin/my-audit.sh"}
        first_event = S.CLI_ADAPTERS[cli]["events"][0][0]
        p.write_text(json.dumps({"version": 1, "hooks": {first_event: [user_hook]}}))

        S.install(cli=cli, yes=True)
        S.install(cli=cli, yes=True)  # idempotent
        data = json.loads(p.read_text())
        for event, module in S.CLI_ADAPTERS[cli]["events"]:
            ours = [e for e in data["hooks"][event] if S._entry_is_ours(e)]
            assert len(ours) == 1
            cmd = ours[0].get("command") or ours[0].get("bash")
            assert f"privacyhook.hooks.{module} --cli {cli}" in cmd
        assert user_hook in data["hooks"][first_event]
        if cli in ("cursor", "copilot"):
            assert data["version"] == 1
        assert S.status(cli)["installed"] is True

        report = S.uninstall(cli=cli, yes=True)
        assert report["removed"] == len(S.CLI_ADAPTERS[cli]["events"])
        data = json.loads(p.read_text())
        assert data["hooks"][first_event] == [user_hook]
        assert S.status(cli)["installed"] is False


def test_copilot_respects_copilot_home(tmp_path, monkeypatch):
    monkeypatch.delenv("PRIVACYHOOK_COPILOT_HOOKS_PATH", raising=False)
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "cop"))
    assert S.settings_path("copilot") == tmp_path / "cop" / "hooks" / "privacyhook.json"


# ---------------------------------------------------------------------------
# Mistral Vibe (TOML block)
# ---------------------------------------------------------------------------

class TestVibe:
    @pytest.fixture
    def toml_path(self, tmp_path, monkeypatch) -> Path:
        p = tmp_path / "vibe" / "hooks.toml"
        monkeypatch.setenv("PRIVACYHOOK_VIBE_HOOKS_PATH", str(p))
        return p

    def test_install_keeps_user_hooks_and_is_valid_toml(self, toml_path):
        tomllib = pytest.importorskip("tomllib")
        toml_path.parent.mkdir()
        user = '[[hooks]]\nname = "deny-rm-rf"\ntype = "pre_tool"\nmatch = "bash"\ncommand = "guard"\n'
        toml_path.write_text(user)
        S.install(cli="vibe", yes=True)
        S.install(cli="vibe", yes=True)
        hooks = tomllib.loads(toml_path.read_text())["hooks"]
        names = [h["name"] for h in hooks]
        assert names == ["deny-rm-rf", "privacyhook-pre-tool", "privacyhook-post-tool"]
        assert "--cli vibe" in hooks[1]["command"]
        assert S.status("vibe")["installed"] is True

        S.uninstall(cli="vibe", yes=True)
        assert tomllib.loads(toml_path.read_text())["hooks"] == [hooks[0]]
        assert S.status("vibe")["installed"] is False

    def test_respects_vibe_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRIVACYHOOK_VIBE_HOOKS_PATH", raising=False)
        monkeypatch.setenv("VIBE_HOME", str(tmp_path / "vh"))
        assert S.settings_path("vibe") == tmp_path / "vh" / "hooks.toml"


# ---------------------------------------------------------------------------
# Cline (one script per event in the hooks directory)
# ---------------------------------------------------------------------------

class TestCline:
    @pytest.fixture
    def hooks_dir(self, tmp_path, monkeypatch) -> Path:
        d = tmp_path / "Cline" / "Hooks"
        monkeypatch.setenv("PRIVACYHOOK_CLINE_HOOKS_DIR", str(d))
        return d

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX script layout")
    def test_install_writes_executable_scripts(self, hooks_dir):
        S.install(cli="cline", yes=True)
        for event, module in S.CLI_ADAPTERS["cline"]["events"]:
            p = hooks_dir / event
            assert os.access(p, os.X_OK)
            assert f"privacyhook.hooks.{module} --cli cline" in p.read_text()
        assert S.status("cline")["installed"] is True
        assert S.uninstall(cli="cline", yes=True)["removed"] == 3
        assert not any(hooks_dir.iterdir())

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX script layout")
    def test_refuses_to_overwrite_user_script(self, hooks_dir):
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "PreToolUse").write_text("#!/bin/sh\necho mine\n")
        with pytest.raises(RuntimeError):
            S.install(cli="cline", yes=True)
        assert S.uninstall(cli="cline", yes=True)["removed"] == 0
        assert (hooks_dir / "PreToolUse").read_text() == "#!/bin/sh\necho mine\n"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX script layout")
    def test_installed_script_runs_the_hook(self, hooks_dir, tmp_path):
        import subprocess
        S.install(cli="cline", yes=True)
        env = {**os.environ, "PRIVACYHOOK_AUDIT_DIR": str(tmp_path / "a"),
               "PRIVACYHOOK_SESSION_ROOT": str(tmp_path / "s"),
               "PYTHONPATH": str(Path(__file__).parent.parent)}
        payload = {"taskId": "t", "preToolUse": {"toolName": "execute_command", "parameters": {"command": "ls"}}}
        proc = subprocess.run([str(hooks_dir / "PreToolUse")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=10)
        assert proc.returncode == 0 and json.loads(proc.stdout) == {"cancel": False}


def test_detect_cli_uses_config_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".vibe").mkdir()
    assert S.detect_cli() == ["cursor", "vibe"]
