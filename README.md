# Bodycam

**The tape for coding agents.** Formerly PrivacyHook.


> Bodycam records every command, file read and secret your coding agents touch, across Claude Code, Codex, Cursor, Copilot and five more. It watches by default and blocks only when you turn enforcement on. Secrets are masked before the model sees them, and the log is HMAC-chained so the tape can be trusted later.
>
> Renamed from PrivacyHook: the `bodycam` command still works as an alias, every `PRIVACYHOOK_*` setting can also be written `BODYCAM_*`, and hooks you already installed keep working.

[![tests](https://img.shields.io/badge/tests-224%20passed-brightgreen)](#testing)
[![python](https://img.shields.io/badge/python-3.11+-blue)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CLIs](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Gemini%20%C2%B7%20Copilot%20%C2%B7%20Cursor%20%C2%B7%20Vibe%20%C2%B7%20%2B4-blueviolet)](#supported-clis)

**Read in:** [Français](docs/README.fr.md) · [中文](docs/README.zh.md) · [日本語](docs/README.ja.md)

---

## Table of contents

- [Why](#why)
- [Supported CLIs](#supported-clis)
- [What it does](#what-it-does)
- [Observe vs enforce](#observe-vs-enforce)
- [Tool-call policy engine](#tool-call-policy-engine)
- [Requirements](#requirements)
- [Installation](#installation)
- [Verify installation](#verify-installation)
- [Usage](#usage)
- [Live monitor](#live-monitor)
- [Team dashboard](#team-dashboard)
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

AI coding agents read your filesystem, run shell commands, and fetch web pages — then feed the results straight back into an LLM context. That's how secrets leak: a `cat .env` in an agent's own reasoning, a stray API key in a curl response, a credential pasted by mistake into a prompt. Prompt-based instructions ("don't read secrets") are not a security boundary — the LLM can be talked out of them. bodycam sits **outside** the model, as CLI hooks that run in plain Python before/after every tool call. The LLM cannot see, disable, or negotiate with a hook — it either lets the call through or it doesn't.

---

## Supported CLIs

What each agent lets a hook do differs, so coverage differs. This table is what bodycam actually does with each one, not what we would like it to do.

| Agent | `--cli` | Tool calls recorded | Sensitive paths / commands (block or `would_block`) | Secrets in tool output | Secrets in prompts |
|---|---|---|---|---|---|
| **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** | `claude` | ✓ | ✓ | masked | ✓ |
| **[OpenAI Codex CLI](https://openai.com/codex)** | `codex` | ✓ | ✓ | masked | ✓ |
| **[Gemini CLI](https://gemini.google.com/cli)** | `gemini` | ✓ | ✓ | masked | — no prompt hook |
| **[OpenCode](https://opencode.ai)** | `opencode` | ✓ | ✓ | masked | — no prompt hook |
| **[GitHub Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference)** | `copilot` | ✓ | ✓ | masked | detected (Copilot ignores prompt-hook answers, so strict mode cannot stop it) |
| **[Mistral Vibe](https://github.com/mistralai/mistral-vibe)** | `vibe` | ✓ | ✓ | masked | — no prompt hook |
| **[Cursor](https://cursor.com/docs/agent/hooks)** | `cursor` | shell commands, file reads | ✓ | detected only¹ | ✓ |
| **[Windsurf](https://docs.devin.ai/desktop/cascade/hooks)** | `windsurf` | commands, file reads and writes | ✓ | — ² | ✓ |
| **[Cline](https://docs.cline.bot/customization/hooks)** | `cline` | ✓ | ✓ | detected only¹ | ✓ |
| **[Aider](https://aider.chat)** | — | not supported: Aider has no hook API to plug into | | | |

¹ Cursor and Cline let a hook read a tool result but not change it. The secret still reaches the model; bodycam records a `secret_detected` event (shown on the team dashboard) instead of masking it.
² Windsurf's post-command hook does not include the command's output.

"Masked" means the secret is replaced by a reversible token like `[WALL:openai_key:1]` before the model sees it. Cline runs hooks only when hooks are enabled in its settings.

---

## What it does

| Hook | Trigger | Action |
|---|---|---|
| **PostToolUse / AfterTool / tool.execute.after** | After `Bash` / `Read` / `WebFetch` (or CLI equivalents) | Replaces detected secrets in tool output with reversible session tokens like `[WALL:openai_key:1]` before the LLM sees them. |
| **PreToolUse / BeforeTool / tool.execute.before** | Before any file/shell tool call | Blocks calls targeting sensitive paths (`.env`, SSH keys, credentials, `*.pem`) **and** evaluates your custom [policy rules](#tool-call-policy-engine). Exit code 2 (or a thrown error for OpenCode) = CLI aborts the call. |
| **UserPromptSubmit** | Every user prompt (agents with a prompt hook, see [Supported CLIs](#supported-clis)) | Scans your prompt for structured secrets. Warns by default, blocks in strict mode. |

Blocking only happens in **enforce** mode. Out of the box bodycam runs in **observe** mode: the same checks run, but a hit is logged as `would_block` and the call goes through — see [Observe vs enforce](#observe-vs-enforce).

Every event — redaction, block, warning, policy match — is recorded in an HMAC-chained audit log (`~/.local/share/privacyhook/audit.jsonl`). Tampering with any entry breaks the chain, and `bodycam audit --verify` proves it.

---

## Observe vs enforce

bodycam starts in **observe** mode so that installing it never breaks an agent session:

| | observe (default) | enforce |
|---|---|---|
| Secret redaction in tool output | on | on |
| Sensitive path / `cat .env` checks | logged as `would_block` | blocked (exit 2) |
| Policy rules with `--action block` | logged as `would_policy_block` | blocked |
| `PRIVACYHOOK_STRICT=1` prompt scan | logged as `would_block`, prompt sent with a warning | prompt blocked |

Watch what your agents actually do (`bodycam audit`, `bodycam monitor`), then switch when you know what you want to stop:

```bash
bodycam mode            # show the current mode
bodycam mode enforce    # start blocking
bodycam mode observe    # back to log-only
```

The mode is saved next to the audit log (`~/.local/share/privacyhook/mode`). `PRIVACYHOOK_MODE=observe|enforce` overrides it for one shell or one CI job.

> **Upgrading from an earlier version?** Earlier releases always blocked. Run `bodycam mode enforce` once to keep that behavior.

---

## Tool-call policy engine

Sensitive-path blocking (`.env`, SSH keys, …) is built in and always on. On top of that, you can define your own **allow / warn / block** rules — no code changes, no redeploy:

```bash
# Block force-pushes to any branch
bodycam policy add --id no-force-push \
  --tool Bash --match 'push.*--force' --action block \
  --reason "force push needs a human"

# Warn (but don't block) writes under any node_modules-like path
bodycam policy add --id watch-writes \
  --tool Write --match-type path_glob --match '*/node_modules/*' \
  --action warn

# List active rules
bodycam policy list

# Dry-run a command against current rules — no side effects
bodycam policy test "git push --force origin main"
# → block  (matched rule 'no-force-push': force push needs a human)

# Remove a rule
bodycam policy remove no-force-push
```

Rules live in `~/.local/share/privacyhook/policy.json`, are evaluated in the order they were added, and the first match wins (no match → allow). Each rule is scoped to a tool (`Bash`, `Read`, `Write`, `*` for all, or `Tool1|Tool2`) and matches either:

- `command_regex` (default) — a regex tested against the shell command (`Bash` calls)
- `path_glob` — a glob tested against the file path (`Read`/`Write`/`Edit` calls)

Every match is written to the audit log as `policy_block` or `policy_warn`, alongside the built-in events, so `bodycam audit` shows a complete picture.

This is the mechanism to reach for when the built-in checks aren't enough for your team: pin dangerous commands, restrict writes to specific paths, or require review for anything touching a directory you care about — all enforced deterministically, outside the model's control.

---

## Requirements

- Python 3.11+
- One of: Claude Code, OpenAI Codex CLI, Gemini CLI, OpenCode, GitHub Copilot CLI, Cursor, Windsurf, Mistral Vibe, Cline
- Zero external Python dependencies — stdlib only (`sqlite3`, `hmac`, `re`, `json`)

---

## Installation

### macOS

```bash
# Install pipx if not already present
brew install pipx

# Install bodycam
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks (auto-detects installed CLIs)
bodycam install
```

### Linux

```bash
# Install pipx
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Restart terminal, then:
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks
bodycam install
```

### Windows (PowerShell)

```powershell
# Install pipx
pip install pipx
pipx ensurepath

# Restart terminal, then:
pipx install git+https://github.com/adrienchristiaen/privacyhook.git

# Register hooks
bodycam install
```

> **Windows note:** Settings are written to `%APPDATA%\Claude\settings.json`,
> `%APPDATA%\Codex\hooks.json`, and `%APPDATA%\Gemini\settings.json` respectively.

### From source (development)

```bash
git clone https://github.com/adrienchristiaen/privacyhook.git
cd bodycam
pipx install --editable .
bodycam install
```

### Targeting a specific CLI

By default `install` auto-detects which CLIs are installed. To target explicitly:

```bash
bodycam install --cli claude     # Claude Code only
bodycam install --cli codex      # Codex CLI only
bodycam install --cli gemini     # Gemini CLI only
bodycam install --cli opencode   # OpenCode only (writes a JS plugin, not a JSON hook)
bodycam install --cli copilot    # GitHub Copilot CLI (~/.copilot/hooks/privacyhook.json, honors $COPILOT_HOME)
bodycam install --cli cursor     # Cursor (~/.cursor/hooks.json)
bodycam install --cli windsurf   # Windsurf (~/.codeium/windsurf/hooks.json)
bodycam install --cli vibe       # Mistral Vibe (a marked [[hooks]] block in ~/.vibe/hooks.toml, honors $VIBE_HOME)
bodycam install --cli cline      # Cline (hook scripts in ~/Documents/Cline/Hooks)
bodycam install --cli all        # all detected CLIs
```

Same flag works for `uninstall` and `status`.

---

## Verify installation

```bash
bodycam status
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
| `bodycam status [--cli auto\|all\|claude\|codex\|gemini\|opencode\|copilot\|cursor\|windsurf\|vibe\|cline]` | Installed hooks per CLI, session DB path, last 5 audit events. |
| `bodycam reveal <token>` | Print the original value behind a session token (session-scoped — dies with the session). |
| `bodycam audit [--verify] [--last N] [--json] [--follow]` | Print the audit log. `--verify` walks the HMAC chain. `--follow` (`-f`) tails new events live, for monitoring in a second terminal. |
| `bodycam audit export [--since DATE] [--until DATE] [--out FILE]` | Export the audit log as CSV — see [compliance export](#compliance-export). |
| `bodycam policy list \| add \| remove \| test` | Manage custom rules — see [policy engine](#tool-call-policy-engine). |
| `bodycam join <url> --token <token> [--name NAME]` | Join your team's dashboard and install hooks in one step — see [team dashboard](#team-dashboard). |
| `bodycam leave` | Stop sending activity to the team dashboard. |
| `bodycam mode [observe\|enforce]` | Show or set the mode — see [observe vs enforce](#observe-vs-enforce). |
| `bodycam monitor [--host] [--port] [--open]` | Serve a live audit-log dashboard on localhost — see [live monitor](#live-monitor). |
| `bodycam uninstall [--cli ...] [--yes]` | Strips only bodycam entries. Other hooks are untouched. |

```
$ bodycam reveal '[WALL:openai_key:1]'
sk-proj-••••••••••••••••••••••••••••••••••••

$ bodycam audit --verify
  ✓ chain intact

$ bodycam audit --follow
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

`bodycam monitor` serves a zero-dependency, local-only dashboard over the live audit log — useful to keep an eye on a long agent session in a second window without polling `audit --follow`.

```bash
bodycam monitor --open
```

![bodycam monitor dashboard](docs/img/monitor-screenshot.png)

Each row is one audit event: which hook fired, what it decided (`block` / `redact` / `warn` / `policy_block`), and why. The `chain intact` indicator re-verifies the HMAC chain on every load — a `chain BROKEN` banner means the log was tampered with after the fact. Binds to `127.0.0.1` only; nothing leaves the machine.

---

## Team dashboard

`bodycam monitor` shows one machine. For a whole team, run the
[control plane](controlplane/README.md) once and have each developer join it:

```bash
# admin, once
docker run -d -p 8957:8957 -v privacyhook-data:/data \
  -e PRIVACYHOOK_CONTROLPLANE_TOKEN=<team-token> privacyhook-controlplane

# each developer, once — checks the token, installs hooks, starts syncing
bodycam join https://cam.acme.internal --token <team-token>
```

On Kubernetes, use the [Helm chart or Terraform module](controlplane/README.md#deploy-on-kubernetes).
Events can also flow into your own stack: Prometheus `/metrics`, OpenTelemetry
(OTLP), or an incremental NDJSON/CSV export for BigQuery, Snowflake and co —
see [Plug into your data platform](controlplane/README.md#plug-into-your-data-platform).

The dashboard at the server's URL shows active developers, agent sessions,
tool calls, secrets masked and what would have been blocked, per developer and
per tool. Only metadata is sent (event type, tool name, agent, developer,
secret categories); commands, paths, prompts and secret values stay on the
developer's machine. Events are sent in the background, so the agent never
waits on the network.

---

## Strict mode

By default the `UserPromptSubmit` hook warns but lets the prompt through. To block (takes effect in [enforce mode](#observe-vs-enforce) only; in observe mode it is logged as `would_block`):

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
  "additionalContext": "⚠ bodycam: 1 sensitive value(s) detected in your prompt
  (categories: email). The prompt was sent unchanged, but tokens have been recorded
  for `bodycam reveal`."}}

=== 6. CLI: status ===
[Claude Code]  ✓ installed
  hooks: PostToolUse · PreToolUse · UserPromptSubmit

SESSION  1 value redacted this session
    [WALL:email:1]  (email)  →  bodycam reveal '[WALL:email:1]'

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
├── settings.py    # multi-CLI install / uninstall (one adapter per agent)
├── cli.py         # argparse entry point
└── hooks/
    ├── _common.py             # stdin/stdout JSON, session, tool name normalization
    ├── adapters.py            # each agent's payload ↔ the Claude Code shape, and its deny/redact answers
    ├── post_tool_use.py       # AfterTool / PostToolUse / tool.execute.after
    ├── pre_tool_use.py        # BeforeTool / PreToolUse / tool.execute.before
    └── user_prompt_submit.py  # UserPromptSubmit (Claude Code + Codex)
```

For every JSON-hooks-array CLI (Claude/Codex/Gemini), `install` writes a hook entry that spawns `python -m privacyhook.hooks.<name> --cli <cli>` per event. OpenCode is the one exception: it loads a JS plugin directly into its own process, so `install --cli opencode` instead generates a thin JS shim (`~/.config/opencode/plugin/privacyhook.js`) that shells out to the same Python hook modules — no logic duplicated in JS.

Cursor, Copilot CLI, Windsurf, Vibe and Cline each send their own JSON shape and expect their own answer (`permission: deny`, `permissionDecision`, `decision: deny`, `cancel: true`, or exit code 2). `hooks/adapters.py` translates both directions, so the detection and policy logic is written once. Cursor, Copilot and Windsurf get entries in their JSON hooks file, Vibe gets a marked `[[hooks]]` block in `hooks.toml`, and Cline gets one small script per event; `uninstall` removes only what bodycam wrote.

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
bodycam audit export --since 2026-01-01 --until 2026-03-31 --out q1-audit.csv
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

**Mitigated** (blocking items apply in [enforce mode](#observe-vs-enforce); in observe mode they are detected and logged):
1. LLM reads secrets via tool output → PostToolUse/AfterTool/tool.execute.after redaction
2. LLM reads `.env` / SSH keys → PreToolUse/BeforeTool/tool.execute.before block
3. LLM runs a command or touches a path your team has flagged → policy engine block/warn
4. Secrets in prompts → prompt scan (Claude Code, Codex, Cursor, Windsurf, Cline; detection only on Copilot CLI)
5. Post-hoc log tampering → HMAC-chained audit

**Not mitigated:**
- Copy-paste propagation (LLM copies secret to another file)
- Full filesystem isolation (use a container)
- Novel secret formats not in `patterns.py`
- Gemini CLI / OpenCode / Mistral Vibe prompts (no prompt hook)
- Secrets in tool output on Cursor and Cline (detected and recorded, not masked) and on Windsurf (output not visible to hooks)
- Aider (no hook API)
- A user with local write access editing `policy.json` or the hooks themselves — this protects against the *LLM* bypassing controls, not against a malicious local operator

---

## Roadmap

- [x] Compliance/audit export (SOC2-style CSV report from the HMAC log)
- [x] OpenCode adapter
- [x] GitHub Copilot CLI, Cursor, Windsurf, Mistral Vibe and Cline adapters
- [ ] Ollama contextual rewriting (200 ms timeout, regex fallback)
- [ ] `Stop` hook with per-session redaction summary
- [ ] Homebrew formula + PyPI release
- [x] GitHub Actions CI (Linux, Python 3.11–3.13) — macOS/Windows still to add
- [x] Helm chart, Terraform module, published image, OpenTelemetry + warehouse export
- [ ] Supply-chain vetting for installed skills/MCP servers

---

## License

MIT — see [LICENSE](LICENSE). The `controlplane/` directory (centralized policy
server) is separately licensed under BSL-1.1, free to self-host, converting to
Apache-2.0 in 2030 — see [LICENSING.md](LICENSING.md) and
[controlplane/LICENSE](controlplane/LICENSE) for the full strategy. Everything
else in this repository stays MIT.
