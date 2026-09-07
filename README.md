# privacyhook

```
    __          __    ____  __             __
   / /_  ____  / /___/ / /_/ /_  ___  ____/ /___  ____  _____
  / __ \/ __ \/ / __  / __/ __ \/ _ \/ __  / __ \/ __ \/ ___/
 / / / / /_/ / / /_/ / /_/ / / /  __/ /_/ / /_/ / /_/ / /
/_/ /_/\____/_/\__,_/\__/_/ /_/\___/\__,_/\____/\____/_/
```

> Privacy-first security layer for AI coding CLIs. Deterministic hooks the LLM cannot bypass — secrets get redacted, sensitive files get blocked, prompts get scanned, and every tool call can be governed by rules you define.

[![tests](https://img.shields.io/badge/tests-122%20passed-brightgreen)](#testing)
[![python](https://img.shields.io/badge/python-3.11+-blue)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CLIs](https://img.shields.io/badge/CLIs-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Gemini%20%C2%B7%20OpenCode-blueviolet)](#supported-clis)

**Read in:** [Français](docs/README.fr.md) · [中文](docs/README.zh.md) · [日本語](docs/README.ja.md)

---

## Table of contents

- [Why](#why)
- [Supported CLIs](#supported-clis)
- [What it does](#what-it-does)
- [Tool-call policy engine](#tool-call-policy-engine)
- [Requirements](#requirements)
- [Installation](#installation)
- [Verify installation](#verify-installation)
- [Usage](#usage)
- [Live monitor](#live-monitor)
- [Strict mode](#strict-mode)
- [End-to-end demo](#end-to-end-demo)
- [Architecture](#architecture)
- [Detected secret categories](#detected-secret-categories)
- [Compliance export](#compliance-export)
- [Testing](#testing)
- [Threat model](#threat-model)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why

AI coding agents read your filesystem, run shell commands, and fetch web pages — then feed the results straight back into an LLM context. That's how secrets leak: a `cat .env` in an agent's own reasoning, a stray API key in a curl response, a credential pasted by mistake into a prompt. Prompt-based instructions ("don't read secrets") are not a security boundary — the LLM can be talked out of them. privacyhook sits **outside** the model, as CLI hooks that run in plain Python before/after every tool call. The LLM cannot see, disable, or negotiate with a hook — it either lets the call through or it doesn't.

---

## Supported CLIs

| CLI | Hook support | Notes |
|---|---|---|
| **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** | Full (3 hooks) | `PostToolUse`, `PreToolUse`, `UserPromptSubmit` |
| **[OpenAI Codex CLI](https://openai.com/codex)** | Full (3 hooks) | Same hook format as Claude Code |
| **[Gemini CLI](https://gemini.google.com/cli)** | Partial (2 hooks) | `BeforeTool`, `AfterTool` — no prompt hook |
| **[OpenCode](https://opencode.ai)** | Partial (2 hooks) | JS plugin bridging `tool.execute.before` / `tool.execute.after` to the same Python hooks — no prompt hook |

---

## What it does

| Hook | Trigger | Action |
|---|---|---|
| **PostToolUse / AfterTool / tool.execute.after** | After `Bash` / `Read` / `WebFetch` (or CLI equivalents) | Replaces detected secrets in tool output with reversible session tokens like `[WALL:openai_key:1]` before the LLM sees them. |
| **PreToolUse / BeforeTool / tool.execute.before** | Before any file/shell tool call | Blocks calls targeting sensitive paths (`.env`, SSH keys, credentials, `*.pem`) **and** evaluates your custom [policy rules](#tool-call-policy-engine). Exit code 2 (or a thrown error for OpenCode) = CLI aborts the call. |
| **UserPromptSubmit** | Every user prompt (Claude Code + Codex only) | Scans your prompt for structured secrets. Warns by default, blocks in strict mode. |

Every event — redaction, block, warning, policy match — is recorded in an HMAC-chained audit log (`~/.local/share/privacyhook/audit.jsonl`). Tampering with any entry breaks the chain, and `privacyhook audit --verify` proves it.

---

## Tool-call policy engine

Sensitive-path blocking (`.env`, SSH keys, …) is built in and always on. On top of that, you can define your own **allow / warn / block** rules — no code changes, no redeploy:

```bash
# Block force-pushes to any branch
privacyhook policy add --id no-force-push \
  --tool Bash --match 'push.*--force' --action block \
  --reason "force push needs a human"

# Warn (but don't block) writes under any node_modules-like path
privacyhook policy add --id watch-writes \
  --tool Write --match-type path_glob --match '*/node_modules/*' \
  --action warn

# List active rules
privacyhook policy list

# Dry-run a command against current rules — no side effects
privacyhook policy test "git push --force origin main"
# → block  (matched rule 'no-force-push': force push needs a human)

# Remove a rule
privacyhook policy remove no-force-push
```

Rules live in `~/.local/share/privacyhook/policy.json`, are evaluated in the order they were added, and the first match wins (no match → allow). Each rule is scoped to a tool (`Bash`, `Read`, `Write`, `*` for all, or `Tool1|Tool2`) and matches either:

- `command_regex` (default) — a regex tested against the shell command (`Bash` calls)
- `path_glob` — a glob tested against the file path (`Read`/`Write`/`Edit` calls)

Every match is written to the audit log as `policy_block` or `policy_warn`, alongside the built-in events, so `privacyhook audit` shows a complete picture.

This is the mechanism to reach for when the built-in checks aren't enough for your team: pin dangerous commands, restrict writes to specific paths, or require review for anything touching a directory you care about — all enforced deterministically, outside the model's control.

---

## Requirements

- Python 3.11+
- One of: Claude Code CLI, OpenAI Codex CLI, Gemini CLI, OpenCode
- Zero external Python dependencies — stdlib only (`sqlite3`, `hmac`, `re`, `json`)

---

## Installation

### macOS

```bash
# Install pipx if not already present
brew install pipx

# Install privacyhook
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks (auto-detects installed CLIs)
privacyhook install
```

### Linux

```bash
# Install pipx
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Restart terminal, then:
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks
privacyhook install
```

### Windows (PowerShell)

```powershell
# Install pipx
pip install pipx
pipx ensurepath

# Restart terminal, then:
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks
privacyhook install
```

> **Windows note:** Settings are written to `%APPDATA%\Claude\settings.json`,
> `%APPDATA%\Codex\hooks.json`, and `%APPDATA%\Gemini\settings.json` respectively.

### From source (development)

```bash
git clone https://github.com/adrienchristiaen/privacyhook.git
cd privacyhook
pipx install --editable .
privacyhook install
```

### Targeting a specific CLI

By default `install` auto-detects which CLIs are installed. To target explicitly:

```bash
privacyhook install --cli claude     # Claude Code only
privacyhook install --cli codex      # Codex CLI only
privacyhook install --cli gemini     # Gemini CLI only
privacyhook install --cli opencode   # OpenCode only (writes a JS plugin, not a JSON hook)
privacyhook install --cli all        # all detected CLIs
```

Same flag works for `uninstall` and `status`.

---

## Verify installation

```bash
privacyhook status
```

Expected output:

```
[Claude Code]  ✓ installed
  /Users/you/.claude/settings.json
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  /tmp/privacyhook/<session-id>/session.db
  0 values redacted this session

RECENT EVENTS
  (none)
```

Open a new CLI session — hooks activate automatically.

---

## Usage

| Command | What it does |
|---|---|
| `privacyhook status [--cli auto\|claude\|codex\|gemini\|opencode\|all]` | Installed hooks per CLI, session DB path, last 5 audit events. |
| `privacyhook reveal <token>` | Print the original value behind a session token (session-scoped — dies with the session). |
| `privacyhook audit [--verify] [--last N] [--json] [--follow]` | Print the audit log. `--verify` walks the HMAC chain. `--follow` (`-f`) tails new events live, for monitoring in a second terminal. |
| `privacyhook audit export [--since DATE] [--until DATE] [--out FILE]` | Export the audit log as CSV — see [compliance export](#compliance-export). |
| `privacyhook policy list \| add \| remove \| test` | Manage custom rules — see [policy engine](#tool-call-policy-engine). |
| `privacyhook monitor [--host] [--port] [--open]` | Serve a live audit-log dashboard on localhost — see [live monitor](#live-monitor). |
| `privacyhook uninstall [--cli ...] [--yes]` | Strips only privacyhook entries. Other hooks are untouched. |

```
$ privacyhook reveal '[WALL:openai_key:1]'
sk-proj-••••••••••••••••••••••••••••••••••••

$ privacyhook audit --verify
  ✓ chain intact

$ privacyhook audit --follow
SESSION AUDIT  —  live (Ctrl-C to stop)
────────────────────────────────────────────────────────────────
  16:11:02  ✗ block  pre-tool  Read  /you/project/.env  →  filename '.env' is sensitive
```

### Emergency disable

Set `PRIVACYHOOK_DISABLED=1` to bypass all hooks (e.g., to write documentation containing example secret patterns):

```bash
export PRIVACYHOOK_DISABLED=1
# ... do your thing ...
unset PRIVACYHOOK_DISABLED
```

---

## Live monitor

`privacyhook monitor` serves a zero-dependency, local-only dashboard over the live audit log — useful to keep an eye on a long agent session in a second window without polling `audit --follow`.

```bash
privacyhook monitor --open
```

![privacyhook monitor dashboard](docs/img/monitor-screenshot.png)

Each row is one audit event: which hook fired, what it decided (`block` / `redact` / `warn` / `policy_block`), and why. The `chain intact` indicator re-verifies the HMAC chain on every load — a `chain BROKEN` banner means the log was tampered with after the fact. Binds to `127.0.0.1` only; nothing leaves the machine.

---

## Strict mode

By default the `UserPromptSubmit` hook warns but lets the prompt through. To block:

```bash
export PRIVACYHOOK_STRICT=1
```

---

## End-to-end demo

```bash
bash scripts/demo.sh
```

Runs in an isolated tmpdir — does not touch your real CLI config. Sample transcript (abridged):

```
=== 1. PostToolUse redact ===
{"hookSpecificOutput": {"hookEventName": "PostToolUse",
  "updatedToolOutput": "OPENAI_API_KEY=[WALL:openai_key:1]\nemail=[WALL:email:1]"}}

=== 2. PreToolUse block .env ===
{"decision": "block", "reason": "path '.env' blocked: filename '.env' is sensitive"}
blocked as expected (exit 2)

=== 3. UserPromptSubmit warn ===
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
  "additionalContext": "⚠ privacyhook: 1 sensitive value(s) detected in your prompt
  (categories: email). The prompt was sent unchanged, but tokens have been recorded
  for `privacyhook reveal`."}}

=== 6. CLI: status ===
[Claude Code]  ✓ installed
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  1 value redacted this session
    [WALL:email:1]  (email)  →  privacyhook reveal '[WALL:email:1]'

RECENT EVENTS
  12:48:27 [demo] claude  ✗ block    pre-tool   Read  .env  →  filename '.env' is sensitive
  12:48:27 [demo] claude  ⚠ warn     prompt     —  →  1× email  ([WALL:email:*])

=== 8. CLI: audit --verify ===
SESSION AUDIT  —  2 events
────────────────────────────────────────────────────────────────
  1 blocked · 1 warned · 1 values replaced with [WALL:*] tokens
  ✓ chain intact
```

---

## Architecture

```
privacyhook/
├── patterns.py    # regex categories + sensitive filename/dir/suffix sets
├── session.py     # SQLite WAL per-session store
├── tokenizer.py   # value <-> [WALL:cat:N] bidirectional, idempotent
├── audit.py       # HMAC-chained JSONL log + verify() + export_csv()
├── workspace.py   # workspace scan + check_path / check_bash (built-in rules)
├── policy.py      # user-defined allow/warn/block rules (policy engine)
├── settings.py    # multi-CLI install / uninstall (Claude/Codex/Gemini/OpenCode adapters)
├── cli.py         # argparse entry point
└── hooks/
    ├── _common.py             # stdin/stdout JSON, session, tool name normalization
    ├── post_tool_use.py       # AfterTool / PostToolUse / tool.execute.after
    ├── pre_tool_use.py        # BeforeTool / PreToolUse / tool.execute.before
    └── user_prompt_submit.py  # UserPromptSubmit (Claude Code + Codex)
```

For every JSON-hooks-array CLI (Claude/Codex/Gemini), `install` writes a hook entry that spawns `python -m privacyhook.hooks.<name> --cli <cli>` per event. OpenCode is the one exception: it loads a JS plugin directly into its own process, so `install --cli opencode` instead generates a thin JS shim (`~/.config/opencode/plugin/privacyhook.js`) that shells out to the same Python hook modules — no logic duplicated in JS.

### CLI adapter mapping

| Feature | Claude Code | Codex CLI | Gemini CLI | OpenCode |
|---|---|---|---|---|
| Post-tool event | `PostToolUse` | `PostToolUse` | `AfterTool` | `tool.execute.after` |
| Pre-tool event | `PreToolUse` | `PreToolUse` | `BeforeTool` | `tool.execute.before` |
| Prompt event | `UserPromptSubmit` | `UserPromptSubmit` | *(not available)* | *(not available)* |
| Shell tool name | `Bash` | `Bash` | `run_shell_command` | `bash` |
| File read tool | `Read` | `Read` | `read_file` | `read` |
| Web fetch tool | `WebFetch` | `WebFetch` | `fetch_webpage` | `webfetch` |
| Install target | JSON hooks array | JSON hooks array + feature flag | JSON hooks array | Generated JS plugin file |
| Timeout unit | seconds | seconds | milliseconds | n/a (in-process) |

---

## Detected secret categories

| Category | Pattern |
|---|---|
| `anthropic_key` | `sk-ant-api03-…` |
| `openai_key` | `sk-proj-…` |
| `github_token` | `ghp_…`, `gho_…`, `ghs_…` |
| `aws_access_key` | `AKIA…` |
| `google_api_key` | `AIza…` |
| `jwt` | `eyJ….eyJ….` |
| `private_key_block` | `-----BEGIN … KEY-----` |
| `slack_token` | `xoxb-…` |
| `email` | `user@domain.tld` |
| `private_ip` | RFC 1918 ranges |
| `internal_hostname` | `*.internal`, `*.corp`, `*.local` |

Extend by adding entries to `privacyhook/patterns.py`. Extend blocking behavior for anything else — a command, a path, a whole category of writes — with the [policy engine](#tool-call-policy-engine) instead, no code change needed.

---

## Compliance export

For SOC2-style external audits, export the HMAC-verified audit log as CSV:

```bash
privacyhook audit export --since 2026-01-01 --until 2026-03-31 --out q1-audit.csv
```

The first line is a `#`-prefixed metadata comment (`chain_verified=true/false`, event count, generation timestamp), so an auditor can see at a glance whether the log was tampered with before trusting the rows beneath it.

---

## Testing

```bash
pip install -e '.[dev]'
pytest -q   # 122 passed
```

---

## Threat model

**Mitigated:**
1. LLM reads secrets via tool output → PostToolUse/AfterTool/tool.execute.after redaction
2. LLM reads `.env` / SSH keys → PreToolUse/BeforeTool/tool.execute.before block
3. LLM runs a command or touches a path your team has flagged → policy engine block/warn
4. Secrets in prompts → UserPromptSubmit scan (Claude Code + Codex)
5. Post-hoc log tampering → HMAC-chained audit

**Not mitigated:**
- Copy-paste propagation (LLM copies secret to another file)
- Full filesystem isolation (use a container)
- Novel secret formats not in `patterns.py`
- Gemini CLI / OpenCode prompts (no `UserPromptSubmit` equivalent)
- A user with local write access editing `policy.json` or the hooks themselves — this protects against the *LLM* bypassing controls, not against a malicious local operator

---

## Roadmap

- [x] Compliance/audit export (SOC2-style CSV report from the HMAC log)
- [x] OpenCode adapter
- [ ] Ollama contextual rewriting (200 ms timeout, regex fallback)
- [ ] `Stop` hook with per-session redaction summary
- [ ] Homebrew formula + PyPI release
- [ ] GitHub Actions CI (Python 3.11–3.14, macOS/Linux/Windows)
- [ ] Supply-chain vetting for installed skills/MCP servers

---

## License

MIT — see [LICENSE](LICENSE). The `controlplane/` directory (centralized policy
server) is separately licensed under BSL-1.1, free to self-host, converting to
Apache-2.0 in 2030 — see [LICENSING.md](LICENSING.md) and
[controlplane/LICENSE](controlplane/LICENSE) for the full strategy. Everything
else in this repository stays MIT.
