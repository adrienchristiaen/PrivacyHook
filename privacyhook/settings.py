"""Manage privacyhook hook registration across Claude Code, Codex CLI, Gemini CLI, and OpenCode.

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
# Detection
# ---------------------------------------------------------------------------

def detect_cli() -> list[str]:
    """Return names of installed CLIs (binary found in PATH)."""
    found = []
    for name, adapter in CLI_ADAPTERS.items():
        if shutil.which(adapter["binary"]):
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
