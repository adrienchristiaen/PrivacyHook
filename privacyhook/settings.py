"""Manage privacyhook hook registration across the supported agent CLIs and IDEs.

Operations:

- `install(cli)` — register hooks for the given CLI adapter, backing up first
- `uninstall(cli)` — strip only entries we own
- `status(cli)` — report whether each hook is registered
- `detect_cli()` — return list of installed CLI names

Hook ownership is tracked by command prefix: anything starting with
`python -m privacyhook.hooks.` or `python3 -m privacyhook.hooks.` is ours;
everything else (user-defined hooks, hooks from other tools) is left alone.
OpenCode is the exception — see `_install_opencode` — it owns a generated
JS plugin file instead, marked with a leading `// privacyhook-managed-plugin`
comment.

Supported CLIs
--------------
claude    — Claude Code  (~/.claude/settings.json)
codex     — OpenAI Codex CLI  (~/.codex/hooks.json)
gemini    — Gemini CLI  (~/.gemini/settings.json)
opencode  — OpenCode  (~/.config/opencode/plugin/privacyhook.js)
cursor    — Cursor  (~/.cursor/hooks.json)
copilot   — GitHub Copilot CLI  (~/.copilot/hooks/privacyhook.json)
windsurf  — Windsurf  (~/.codeium/windsurf/hooks.json)
vibe      — Mistral Vibe  (~/.vibe/hooks.toml, a marked [[hooks]] block)
cline     — Cline  (~/Documents/Cline/Hooks/<Event> scripts)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from copy import deepcopy
from pathlib import Path

# ---------------------------------------------------------------------------
# CLI adapter definitions
# ---------------------------------------------------------------------------

# Each adapter describes where settings live and which event names to use.
# timeout is in seconds for Claude/Codex, milliseconds for Gemini.
CLI_ADAPTERS: dict[str, dict] = {
    "claude": {
        "label": "Claude Code",
        "binary": "claude",
        "settings_env": "PRIVACYHOOK_SETTINGS_PATH",
        "default_settings": "~/.claude/settings.json",
        "windows_settings": "~/AppData/Roaming/Claude/settings.json",
        "hooks_key": "hooks",
        "pre_event": "PreToolUse",
        "post_event": "PostToolUse",
        "prompt_event": "UserPromptSubmit",
        "pre_matcher": "Bash|Read|Edit|Write|WebFetch",
        "post_matcher": "Bash|Read|WebFetch",
        "prompt_matcher": "*",
        "timeout": 5,
        "timeout_unit": "seconds",
    },
    "codex": {
        "label": "OpenAI Codex CLI",
        "binary": "codex",
        "settings_env": "PRIVACYHOOK_CODEX_SETTINGS_PATH",
        "default_settings": "~/.codex/hooks.json",
        "windows_settings": "~/AppData/Roaming/Codex/hooks.json",
        "hooks_key": "hooks",
        "pre_event": "PreToolUse",
        "post_event": "PostToolUse",
        "prompt_event": "UserPromptSubmit",
        "pre_matcher": "Bash|Edit|apply_patch|Write",
        "post_matcher": "Bash|WebFetch",
        "prompt_matcher": "*",
        "timeout": 5,
        "timeout_unit": "seconds",
    },
    "gemini": {
        "label": "Gemini CLI",
        "binary": "gemini",
        "settings_env": "PRIVACYHOOK_GEMINI_SETTINGS_PATH",
        "default_settings": "~/.gemini/settings.json",
        "windows_settings": "~/AppData/Roaming/Gemini/settings.json",
        "hooks_key": "hooks",
        "pre_event": "BeforeTool",
        "post_event": "AfterTool",
        "prompt_event": None,  # no UserPromptSubmit equivalent
        "pre_matcher": "run_shell_command|run_code|write_file|replace_in_file|read_file",
        "post_matcher": "run_shell_command|run_code|read_file|fetch_webpage",
        "prompt_matcher": None,
        "timeout": 5000,  # milliseconds
        "timeout_unit": "milliseconds",
    },
    "opencode": {
        # OpenCode has no shell-command-hooks-via-JSON-stdin settings file
        # like the other three adapters — it loads a JS/TS plugin module in
        # its own process instead. `install`/`uninstall`/`status` special-case
        # this adapter (see _install_opencode etc.) rather than going through
        # the generic hooks-array JSON path the others share.
        "label": "OpenCode",
        "binary": "opencode",
        "settings_env": "PRIVACYHOOK_OPENCODE_PLUGIN_PATH",
        "default_settings": "~/.config/opencode/plugin/privacyhook.js",
        "windows_settings": "~/AppData/Roaming/opencode/plugin/privacyhook.js",
        "kind": "js_plugin",
    },
    # The adapters below each have their own config format; `kind` picks the
    # installer and `events` lists (event name, hook module) pairs. Their
    # stdin/stdout dialects are translated in privacyhook/hooks/adapters.py.
    "cursor": {
        "label": "Cursor",
        "binary": "cursor",
        "detect_dir": "~/.cursor",
        "settings_env": "PRIVACYHOOK_CURSOR_HOOKS_PATH",
        "default_settings": "~/.cursor/hooks.json",
        "windows_settings": "~/.cursor/hooks.json",
        "kind": "flat_json",
        "version": 1,
        "events": [
            ("beforeShellExecution", "pre_tool_use"),
            ("beforeReadFile", "pre_tool_use"),
            ("afterShellExecution", "post_tool_use"),
            ("beforeSubmitPrompt", "user_prompt_submit"),
        ],
    },
    "copilot": {
        "label": "GitHub Copilot CLI",
        "binary": "copilot",
        "detect_dir": "~/.copilot",
        "settings_env": "PRIVACYHOOK_COPILOT_HOOKS_PATH",
        "home_env": ("COPILOT_HOME", "hooks/privacyhook.json"),
        "default_settings": "~/.copilot/hooks/privacyhook.json",
        "windows_settings": "~/.copilot/hooks/privacyhook.json",
        "kind": "flat_json",
        "version": 1,
        "events": [
            ("preToolUse", "pre_tool_use"),
            ("postToolUse", "post_tool_use"),
            ("userPromptSubmitted", "user_prompt_submit"),
        ],
    },
    "windsurf": {
        "label": "Windsurf",
        "binary": "windsurf",
        "detect_dir": "~/.codeium/windsurf",
        "settings_env": "PRIVACYHOOK_WINDSURF_HOOKS_PATH",
        "default_settings": "~/.codeium/windsurf/hooks.json",
        "windows_settings": "~/.codeium/windsurf/hooks.json",
        "kind": "flat_json",
        # Windsurf's post hooks carry no tool output, so there is nothing to
        # redact; pre hooks cover paths, commands and prompts.
        "events": [
            ("pre_run_command", "pre_tool_use"),
            ("pre_read_code", "pre_tool_use"),
            ("pre_write_code", "pre_tool_use"),
            ("pre_user_prompt", "user_prompt_submit"),
        ],
    },
    "vibe": {
        "label": "Mistral Vibe",
        "binary": "vibe",
        "detect_dir": "~/.vibe",
        "settings_env": "PRIVACYHOOK_VIBE_HOOKS_PATH",
        "home_env": ("VIBE_HOME", "hooks.toml"),
        "default_settings": "~/.vibe/hooks.toml",
        "windows_settings": "~/.vibe/hooks.toml",
        "kind": "toml_block",
        # Vibe has no prompt hook.
        "events": [
            ("pre_tool", "pre_tool_use", "re:^(bash|read_file|write_file|edit)$"),
            ("post_tool", "post_tool_use", "re:^(bash|read_file|web_fetch)$"),
        ],
    },
    "cline": {
        "label": "Cline",
        "binary": "cline",
        "detect_dir": "~/Documents/Cline",
        "settings_env": "PRIVACYHOOK_CLINE_HOOKS_DIR",
        "default_settings": "~/Documents/Cline/Hooks",
        "windows_settings": "~/Documents/Cline/Hooks",
        "kind": "script_dir",
        "events": [
            ("PreToolUse", "pre_tool_use"),
            ("PostToolUse", "post_tool_use"),
            ("UserPromptSubmit", "user_prompt_submit"),
        ],
    },
}

# Agent tools we were asked about that expose no hook API to plug into.
UNSUPPORTED_CLIS = {
    "aider": "Aider has no hook API: it cannot report tool calls or let a hook redact output.",
}

SUPPORTED_CLIS = list(CLI_ADAPTERS.keys())


def _hook_command(module: str, cli: str) -> str:
    # Use the exact Python that's running privacyhook (pipx venv, conda env, etc.)
    # so the hook process can always import privacyhook regardless of PATH.
    # `--cli` tags which adapter installed this hook: Codex CLI sets no
    # identifying env var at hook runtime (unlike Claude Code), so without
    # this the hook can't tell Codex apart from "unknown" at all.
    return f"{sys.executable} -m {module} --cli {cli}"


OUR_COMMAND_PREFIXES = (
    "python -m privacyhook.hooks.",
    "python3 -m privacyhook.hooks.",
    f"{sys.executable} -m privacyhook.hooks.",
)


def _is_ours(command: str) -> bool:
    return any(command.startswith(p) for p in OUR_COMMAND_PREFIXES)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def settings_path(cli: str = "claude") -> Path:
    adapter = CLI_ADAPTERS[cli]
    env_key = adapter.get("settings_env")
    if env_key:
        override = os.environ.get(env_key)
        if override:
            return Path(override)
    if adapter.get("home_env"):
        home_var, rel = adapter["home_env"]
        if os.environ.get(home_var):
            return Path(os.environ[home_var]).expanduser() / rel
    raw = adapter["windows_settings"] if sys.platform == "win32" else adapter["default_settings"]
    return Path(raw).expanduser()


def backup_path(cli: str = "claude") -> Path:
    p = settings_path(cli)
    return p.with_suffix(p.suffix + ".privacyhook.bak")


def _codex_config_path() -> Path:
    override = os.environ.get("PRIVACYHOOK_CODEX_CONFIG_PATH")
    if override:
        return Path(override)
    return Path("~/.codex/config.toml").expanduser()


def _codex_feature_flag_enabled() -> bool:
    path = _codex_config_path()
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return re.search(r"^\s*codex_hooks\s*=\s*true", text, re.MULTILINE) is not None


def _ensure_codex_feature_flag() -> None:
    """Codex CLI hooks are inert unless `codex_hooks = true` under [features]
    in ~/.codex/config.toml. Without this, an installed hooks.json silently
    does nothing — so `install(cli="codex")` sets it, backing up first."""
    path = _codex_config_path()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if re.search(r"^\s*codex_hooks\s*=\s*true", text, re.MULTILINE):
        return
    if path.exists():
        path.with_suffix(path.suffix + ".privacyhook.bak").write_text(text, encoding="utf-8")
    if re.search(r"^\s*\[features\]", text, re.MULTILINE):
        text = re.sub(r"^\s*\[features\]", "[features]\ncodex_hooks = true", text, count=1, flags=re.MULTILINE)
    else:
        sep = "\n\n" if text.strip() else ""
        text = text.rstrip("\n") + sep + "[features]\ncodex_hooks = true\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# OpenCode adapter (JS plugin file, not a JSON hooks array)
# ---------------------------------------------------------------------------

_OPENCODE_MARKER = "// privacyhook-managed-plugin"

_OPENCODE_PLUGIN_TEMPLATE = '''\
{marker} — generated by `privacyhook install --cli opencode`.
// Do not edit by hand: reinstalling overwrites this file.
//
// Bridges OpenCode's tool.execute.before/after hooks to privacyhook's
// existing Python hook processes (same JSON-over-stdin protocol used by
// the Claude Code / Codex / Gemini adapters), so detection/blocking/
// redaction logic lives in one place.
import {{ execFileSync }} from "node:child_process"

const PYTHON = {python!r}

function runHook(module, payload) {{
  try {{
    const out = execFileSync(PYTHON, ["-m", module, "--cli", "opencode"], {{
      input: JSON.stringify(payload),
      encoding: "utf-8",
    }})
    return out ? JSON.parse(out) : null
  }} catch (err) {{
    // Non-zero exit == block. privacyhook writes {{"decision":"block","reason":...}}
    // to stdout even on block, so prefer that over raw stderr when present.
    let reason = err.stderr ? String(err.stderr).trim() : "blocked by privacyhook"
    if (err.stdout) {{
      try {{
        const decision = JSON.parse(String(err.stdout))
        if (decision.reason) reason = decision.reason
      }} catch {{}}
    }}
    throw new Error(reason)
  }}
}}

export const PrivacyHook = async () => {{
  return {{
    "tool.execute.before": async (input, output) => {{
      runHook("privacyhook.hooks.pre_tool_use", {{
        session_id: input.sessionID,
        tool_name: input.tool,
        tool_input: output.args,
      }})
    }},
    "tool.execute.after": async (input, output) => {{
      const result = runHook("privacyhook.hooks.post_tool_use", {{
        session_id: input.sessionID,
        tool_name: input.tool,
        tool_response: output.output,
      }})
      const updated = result && result.hookSpecificOutput && result.hookSpecificOutput.updatedToolOutput
      if (typeof updated === "string") {{
        output.output = updated
      }}
    }},
  }}
}}
'''


def _is_ours_opencode_plugin(text: str) -> bool:
    return text.lstrip().startswith(_OPENCODE_MARKER)


def _install_opencode(path: Path, *, dry_run: bool) -> dict:
    content = _OPENCODE_PLUGIN_TEMPLATE.format(marker=_OPENCODE_MARKER, python=sys.executable)
    existed = path.exists()
    if existed and not _is_ours_opencode_plugin(path.read_text(encoding="utf-8")):
        raise RuntimeError(
            f"{path} exists and isn't a privacyhook-managed plugin — refusing to overwrite. "
            f"Remove it manually first if you want privacyhook to manage this file."
        )
    report = {
        "cli": "opencode",
        "added": 2,  # tool.execute.before + tool.execute.after
        "dry_run": dry_run,
        "path": str(path),
        "diff_summary": "+1 privacyhook plugin file for opencode (before/after tool hooks)",
    }
    if dry_run:
        return report
    if existed:
        backup_path("opencode").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return report


def _uninstall_opencode(path: Path) -> dict:
    if not path.exists():
        return {"cli": "opencode", "removed": 0, "path": str(path)}
    if not _is_ours_opencode_plugin(path.read_text(encoding="utf-8")):
        return {"cli": "opencode", "removed": 0, "path": str(path)}
    path.unlink()
    return {"cli": "opencode", "removed": 2, "path": str(path)}


def _status_opencode(path: Path) -> dict:
    installed = path.exists() and _is_ours_opencode_plugin(path.read_text(encoding="utf-8"))
    return {
        "cli": "opencode",
        "label": CLI_ADAPTERS["opencode"]["label"],
        "installed": installed,
        "hooks": ["tool.execute.before", "tool.execute.after"] if installed else [],
        "path": str(path),
    }


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Hook entry builders
# ---------------------------------------------------------------------------

def _hooks_spec(cli: str) -> list[dict]:
    a = CLI_ADAPTERS[cli]
    specs = []
    if a["post_event"]:
        specs.append({
            "bucket": a["post_event"],
            "matcher": a["post_matcher"],
            "module": "privacyhook.hooks.post_tool_use",
            "timeout": a["timeout"],
        })
    if a["pre_event"]:
        specs.append({
            "bucket": a["pre_event"],
            "matcher": a["pre_matcher"],
            "module": "privacyhook.hooks.pre_tool_use",
            "timeout": a["timeout"],
        })
    if a["prompt_event"]:
        specs.append({
            "bucket": a["prompt_event"],
            "matcher": a["prompt_matcher"],
            "module": "privacyhook.hooks.user_prompt_submit",
            "timeout": a["timeout"],
        })
    return specs


def _build_hook_entry(spec: dict, cli: str) -> dict:
    entry: dict = {
        "matcher": spec["matcher"],
        "hooks": [
            {
                "type": "command",
                "command": _hook_command(spec["module"], cli),
                "timeout": spec["timeout"],
            }
        ],
    }
    return entry


def _strip_ours(bucket_entries: list) -> list:
    cleaned: list = []
    for entry in bucket_entries:
        hooks = entry.get("hooks", [])
        kept = [h for h in hooks if not _is_ours(h.get("command", ""))]
        if kept:
            new_entry = dict(entry)
            new_entry["hooks"] = kept
            cleaned.append(new_entry)
        elif not hooks:
            cleaned.append(entry)
    return cleaned


# ---------------------------------------------------------------------------
# Cursor, Copilot CLI, Windsurf (flat JSON), Vibe (TOML), Cline (scripts)
# ---------------------------------------------------------------------------

def _powershell_command(module: str, cli: str) -> str:
    return f'& "{sys.executable}" -m {module} --cli {cli}'


def _flat_entry(cli: str, module: str) -> dict:
    cmd = _hook_command(f"privacyhook.hooks.{module}", cli)
    if cli == "copilot":
        return {"type": "command", "bash": cmd,
                "powershell": _powershell_command(f"privacyhook.hooks.{module}", cli), "timeoutSec": 10}
    if cli == "windsurf":
        return {"command": cmd, "powershell": _powershell_command(f"privacyhook.hooks.{module}", cli),
                "show_output": False}
    return {"command": cmd}


def _entry_is_ours(entry: dict) -> bool:
    return any(_is_ours(str(entry.get(k, ""))) or "-m privacyhook.hooks." in str(entry.get(k, ""))
               for k in ("command", "bash", "powershell"))


def _install_flat_json(cli: str, path: Path, *, dry_run: bool) -> dict:
    adapter = CLI_ADAPTERS[cli]
    data = _load(path)
    before = deepcopy(data)
    if adapter.get("version") is not None:
        data.setdefault("version", adapter["version"])
    hooks_root = data.setdefault("hooks", {})
    for event, _ in adapter["events"]:
        hooks_root[event] = [e for e in hooks_root.get(event, []) if not _entry_is_ours(e)]
    for event, module in adapter["events"]:
        hooks_root[event].append(_flat_entry(cli, module))
    added = len(adapter["events"])
    report = {"cli": cli, "added": added, "dry_run": dry_run, "path": str(path),
              "diff_summary": f"+{added} privacyhook hook entries for {cli}",
              "before": before, "after": data}
    if dry_run:
        return report
    if path.exists():
        backup_path(cli).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return report


def _uninstall_flat_json(cli: str, path: Path) -> dict:
    data = _load(path)
    hooks_root = data.get("hooks", {})
    removed = 0
    for event in list(hooks_root):
        kept = [e for e in hooks_root[event] if not _entry_is_ours(e)]
        removed += len(hooks_root[event]) - len(kept)
        hooks_root[event] = kept
    if removed:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"cli": cli, "removed": removed, "path": str(path)}


def _status_flat_json(cli: str, path: Path) -> dict:
    hooks_root = _load(path).get("hooks", {})
    events = [ev for ev, _ in CLI_ADAPTERS[cli]["events"]]
    found = [ev for ev in events if any(_entry_is_ours(e) for e in hooks_root.get(ev, []))]
    return {"cli": cli, "label": CLI_ADAPTERS[cli]["label"], "installed": len(found) == len(events),
            "hooks": found, "path": str(path)}


_TOML_BEGIN = "# >>> privacyhook (managed block, removed by `privacyhook uninstall --cli vibe`)"
_TOML_END = "# <<< privacyhook"
_TOML_BLOCK_RE = re.compile(rf"\n*{re.escape(_TOML_BEGIN)}.*?{re.escape(_TOML_END)}\n?", re.DOTALL)


def _vibe_block() -> str:
    lines = [_TOML_BEGIN]
    for event, module, match in CLI_ADAPTERS["vibe"]["events"]:
        # JSON string escapes are valid TOML basic-string escapes.
        lines += [
            "[[hooks]]",
            f'name = "privacyhook-{event.replace("_", "-")}"',
            f'type = "{event}"',
            f"match = {json.dumps(match)}",
            f"command = {json.dumps(_hook_command(f'privacyhook.hooks.{module}', 'vibe'))}",
            "timeout = 10.0",
            "",
        ]
    lines[-1] = _TOML_END
    return "\n".join(lines) + "\n"


def _install_toml_block(path: Path, *, dry_run: bool) -> dict:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    stripped = _TOML_BLOCK_RE.sub("\n", text).rstrip("\n")
    new_text = (stripped + "\n\n" if stripped else "") + _vibe_block()
    added = len(CLI_ADAPTERS["vibe"]["events"])
    report = {"cli": "vibe", "added": added, "dry_run": dry_run, "path": str(path),
              "diff_summary": f"+{added} privacyhook [[hooks]] entries for vibe",
              "before": text, "after": new_text}
    if dry_run:
        return report
    if path.exists():
        backup_path("vibe").write_text(text, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return report


def _uninstall_toml_block(path: Path) -> dict:
    if not path.exists():
        return {"cli": "vibe", "removed": 0, "path": str(path)}
    text = path.read_text(encoding="utf-8")
    if _TOML_BEGIN not in text:
        return {"cli": "vibe", "removed": 0, "path": str(path)}
    rest = _TOML_BLOCK_RE.sub("\n", text).strip("\n")
    path.write_text(rest + "\n" if rest else "", encoding="utf-8")
    return {"cli": "vibe", "removed": len(CLI_ADAPTERS["vibe"]["events"]), "path": str(path)}


def _status_toml_block(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    installed = _TOML_BEGIN in text and _TOML_END in text
    return {"cli": "vibe", "label": CLI_ADAPTERS["vibe"]["label"], "installed": installed,
            "hooks": [e[0] for e in CLI_ADAPTERS["vibe"]["events"]] if installed else [],
            "path": str(path)}


_SCRIPT_MARKER = "privacyhook-managed-hook"


def _script_path(directory: Path, event: str) -> Path:
    return directory / (f"{event}.ps1" if sys.platform == "win32" else event)


def _script_content(module: str) -> str:
    if sys.platform == "win32":
        return (f"# {_SCRIPT_MARKER}: generated by `privacyhook install --cli cline`.\n"
                f"$payload = [Console]::In.ReadToEnd()\n"
                f"$payload | {_powershell_command(f'privacyhook.hooks.{module}', 'cline')}\n"
                f"exit $LASTEXITCODE\n")
    return (f"#!/bin/sh\n# {_SCRIPT_MARKER}: generated by `privacyhook install --cli cline`.\n"
            f'exec "{sys.executable}" -m privacyhook.hooks.{module} --cli cline\n')


def _script_is_ours(path: Path) -> bool:
    try:
        return _SCRIPT_MARKER in path.read_text(encoding="utf-8")[:300]
    except OSError:
        return False


def _install_script_dir(directory: Path, *, dry_run: bool) -> dict:
    events = CLI_ADAPTERS["cline"]["events"]
    for event, _ in events:
        p = _script_path(directory, event)
        if p.exists() and not _script_is_ours(p):
            raise RuntimeError(
                f"{p} exists and isn't a privacyhook-managed hook — refusing to overwrite. "
                f"Merge it by hand or move it away first."
            )
    report = {"cli": "cline", "added": len(events), "dry_run": dry_run, "path": str(directory),
              "diff_summary": f"+{len(events)} privacyhook hook scripts for cline",
              "after": {str(_script_path(directory, e)): _script_content(m) for e, m in events}}
    if dry_run:
        return report
    directory.mkdir(parents=True, exist_ok=True)
    for event, module in events:
        p = _script_path(directory, event)
        p.write_text(_script_content(module), encoding="utf-8")
        p.chmod(0o755)
    return report


def _uninstall_script_dir(directory: Path) -> dict:
    removed = 0
    for event, _ in CLI_ADAPTERS["cline"]["events"]:
        p = _script_path(directory, event)
        if p.exists() and _script_is_ours(p):
            p.unlink()
            removed += 1
    return {"cli": "cline", "removed": removed, "path": str(directory)}


def _status_script_dir(directory: Path) -> dict:
    events = [e for e, _ in CLI_ADAPTERS["cline"]["events"]]
    found = [e for e in events if _script_is_ours(_script_path(directory, e))]
    return {"cli": "cline", "label": CLI_ADAPTERS["cline"]["label"], "installed": len(found) == len(events),
            "hooks": found, "path": str(directory)}


_KIND_HANDLERS = {
    "flat_json": (lambda cli, p, dry: _install_flat_json(cli, p, dry_run=dry), _uninstall_flat_json, _status_flat_json),
    "toml_block": (lambda cli, p, dry: _install_toml_block(p, dry_run=dry),
                   lambda cli, p: _uninstall_toml_block(p), lambda cli, p: _status_toml_block(p)),
    "script_dir": (lambda cli, p, dry: _install_script_dir(p, dry_run=dry),
                   lambda cli, p: _uninstall_script_dir(p), lambda cli, p: _status_script_dir(p)),
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_cli() -> list[str]:
    """Return names of installed CLIs (binary found in PATH)."""
    found = []
    for name, adapter in CLI_ADAPTERS.items():
        # IDE-based agents (Cursor, Windsurf, Cline) often have no binary on
        # PATH; their config directory is the signal instead.
        if shutil.which(adapter["binary"]) or (
            adapter.get("detect_dir") and Path(adapter["detect_dir"]).expanduser().is_dir()
        ):
            found.append(name)
    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install(cli: str = "claude", *, dry_run: bool = False, yes: bool = False) -> dict:
    """Register privacyhook hooks for `cli`. Returns a report dict."""
    if cli not in CLI_ADAPTERS:
        raise ValueError(f"unknown CLI {cli!r}, choose from {SUPPORTED_CLIS}")
    if CLI_ADAPTERS[cli].get("kind") == "js_plugin":
        return _install_opencode(settings_path(cli), dry_run=dry_run)
    if CLI_ADAPTERS[cli].get("kind") in _KIND_HANDLERS:
        return _KIND_HANDLERS[CLI_ADAPTERS[cli]["kind"]][0](cli, settings_path(cli), dry_run)
    path = settings_path(cli)
    data = _load(path)
    before = deepcopy(data)

    hooks_root = data.setdefault(CLI_ADAPTERS[cli]["hooks_key"], {})
    specs = _hooks_spec(cli)
    added = 0
    for spec in specs:
        bucket = hooks_root.setdefault(spec["bucket"], [])
        stripped = _strip_ours(bucket)
        stripped.append(_build_hook_entry(spec, cli))
        hooks_root[spec["bucket"]] = stripped
        added += 1

    report = {
        "cli": cli,
        "added": added,
        "dry_run": dry_run,
        "path": str(path),
        "diff_summary": f"+{added} privacyhook hook entries for {cli}",
        "before": before,
        "after": data,
    }
    if cli == "codex":
        report["codex_feature_flag_needed"] = not _codex_feature_flag_enabled()
    if dry_run:
        return report

    if path.exists():
        backup_path(cli).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if cli == "codex":
        _ensure_codex_feature_flag()
        report["codex_feature_flag_needed"] = False

    return report


def uninstall(cli: str = "claude", *, yes: bool = False) -> dict:
    if cli not in CLI_ADAPTERS:
        raise ValueError(f"unknown CLI {cli!r}")
    if CLI_ADAPTERS[cli].get("kind") == "js_plugin":
        return _uninstall_opencode(settings_path(cli))
    if CLI_ADAPTERS[cli].get("kind") in _KIND_HANDLERS:
        return _KIND_HANDLERS[CLI_ADAPTERS[cli]["kind"]][1](cli, settings_path(cli))
    path = settings_path(cli)
    data = _load(path)
    hooks_root = data.get(CLI_ADAPTERS[cli]["hooks_key"], {})
    removed = 0
    for spec in _hooks_spec(cli):
        bucket = hooks_root.get(spec["bucket"])
        if not bucket:
            continue
        original_n = sum(len(e.get("hooks", [])) for e in bucket)
        hooks_root[spec["bucket"]] = _strip_ours(bucket)
        new_n = sum(len(e.get("hooks", [])) for e in hooks_root[spec["bucket"]])
        removed += original_n - new_n
    if path.exists():
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"cli": cli, "removed": removed, "path": str(path)}


def status(cli: str = "claude") -> dict:
    if cli not in CLI_ADAPTERS:
        raise ValueError(f"unknown CLI {cli!r}")
    if CLI_ADAPTERS[cli].get("kind") == "js_plugin":
        return _status_opencode(settings_path(cli))
    if CLI_ADAPTERS[cli].get("kind") in _KIND_HANDLERS:
        return _KIND_HANDLERS[CLI_ADAPTERS[cli]["kind"]][2](cli, settings_path(cli))
    path = settings_path(cli)
    data = _load(path)
    hooks_root = data.get(CLI_ADAPTERS[cli]["hooks_key"], {})
    installed_buckets: list[str] = []
    for spec in _hooks_spec(cli):
        bucket = hooks_root.get(spec["bucket"], [])
        for entry in bucket:
            for h in entry.get("hooks", []):
                if _is_ours(h.get("command", "")):
                    installed_buckets.append(spec["bucket"])
                    break
            if spec["bucket"] in installed_buckets:
                break
    return {
        "cli": cli,
        "label": CLI_ADAPTERS[cli]["label"],
        "installed": len(installed_buckets) == len(_hooks_spec(cli)),
        "hooks": installed_buckets,
        "path": str(path),
    }
