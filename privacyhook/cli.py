"""privacyhook CLI entry point.

Subcommands:

- install      — register the three hooks in ~/.claude/settings.json
- uninstall    — strip privacyhook hooks (leaves user hooks intact)
- status       — show installed hooks, session dir, recent events
- reveal TOK   — print the original value for a session token
- audit        — print the audit log, with --verify to check the HMAC chain
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import settings as S
from .audit import AuditLog, generate_key
from .policy import Rule, PolicyEngine, VALID_ACTIONS, VALID_MATCH_TYPES
from .remote_policy import RemotePolicySource
from .session import SessionStore, session_db_path, session_root
from .settings import SUPPORTED_CLIS, detect_cli

# ── terminal colours (no external deps) ─────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
GREEN  = lambda t: _c("32", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)
CYAN   = lambda t: _c("36", t)

# ── event pretty-printing ────────────────────────────────────────────────────

_EVENT_ICON = {
    "block": RED("✗"),
    "policy_block": RED("✗"),
    "redact": YELLOW("⚙"),
    "warn": YELLOW("⚠"),
    "policy_warn": YELLOW("⚠"),
    "allow": GREEN("✓"),
}
_HOOK_SHORT = {
    "pre_tool_use":       "pre-tool ",
    "post_tool_use":      "post-tool",
    "user_prompt_submit": "prompt   ",
}


def _fmt_ts(ts: float) -> str:
    # local time, with date if not today
    local = datetime.fromtimestamp(ts)
    now = datetime.now()
    if local.date() == now.date():
        return local.strftime("%H:%M:%S")
    return local.strftime("%m-%d %H:%M")


def _fmt_event(e: dict) -> str:
    icon    = _EVENT_ICON.get(e.get("event", ""), "·")
    hook    = _HOOK_SHORT.get(e.get("hook", ""), e.get("hook", "")[:9])
    event   = e.get("event", "?")
    tool    = e.get("tool") or "—"
    cats    = e.get("categories") or []
    count   = e.get("count", 0)
    reason  = e.get("reason", "")
    ts      = _fmt_ts(e["ts"]) if "ts" in e else "??:??:??"
    sid     = e.get("session", "") or "default"
    src_cli = e.get("cli", "")
    sid_str = DIM(f" [{sid[:8]}]")
    cli_str = DIM(f" {src_cli}") if src_cli and src_cli != "unknown" else ""

    target  = e.get("target", "")

    # detail line
    if event in ("block", "policy_block"):
        target_str = f"  {DIM(target)}" if target else ""
        detail = f"{BOLD(tool)}{target_str}  →  {reason or 'blocked'}"
    elif event == "policy_warn":
        target_str = f"  {DIM(target)}" if target else ""
        detail = f"{BOLD(tool)}{target_str}  →  {reason or 'policy warning'}"
    elif event in ("redact", "warn") and cats:
        tokens = ", ".join(f"[WALL:{c}:*]" for c in cats[:3])
        detail = f"{BOLD(tool)}  →  {count}× {', '.join(cats)}  ({tokens})"
    else:
        detail = f"{BOLD(tool)}"

    return f"  {DIM(ts)}{sid_str}{cli_str}  {icon} {event:<7}  {DIM(hook)}  {detail}"


def _exit(msg: str, code: int = 1) -> int:
    sys.stderr.write(f"privacyhook: {msg}\n")
    return code


def _confirm(msg: str, yes: bool) -> bool:
    if yes:
        return True
    sys.stderr.write(f"{msg} [y/N] ")
    sys.stderr.flush()
    try:
        ans = input().strip().lower()
    except EOFError:
        return False
    return ans in {"y", "yes"}


def _resolve_clis(cli_arg: str) -> list[str]:
    if cli_arg == "all":
        found = detect_cli()
        return found if found else ["claude"]
    if cli_arg == "auto":
        found = detect_cli()
        return [found[0]] if found else ["claude"]
    return [cli_arg]


def cmd_install(args: argparse.Namespace) -> int:
    clis = _resolve_clis(args.cli)
    for cli in clis:
        report = S.install(cli=cli, dry_run=True, yes=args.yes)
        if args.dry_run:
            print(f"--- {cli} ({report['path']}) ---")
            print(json.dumps(report["after"], indent=2))
            continue
        if not _confirm(
            f"register privacyhook hooks in {report['path']}?", args.yes
        ):
            return _exit("aborted")
        report = S.install(cli=cli, yes=True)
        print(f"[{cli}] installed {report['added']} hooks in {report['path']}")
        if cli == "codex" and report.get("codex_feature_flag_needed") is False:
            print(DIM(f"  [codex] enabled codex_hooks in ~/.codex/config.toml"))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    clis = _resolve_clis(args.cli)
    for cli in clis:
        if not _confirm(f"remove privacyhook hooks from {cli}?", args.yes):
            return _exit("aborted")
        report = S.uninstall(cli=cli, yes=True)
        print(f"[{cli}] removed {report['removed']} hook command(s) from {report['path']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    clis = _resolve_clis(getattr(args, "cli", "auto"))
    print()

    # ── hooks per CLI ────────────────────────────────────────────────────────
    for cli in clis:
        st = S.status(cli=cli)
        badge = GREEN("✓ installed") if st["installed"] else RED("✗ not installed")
        print(BOLD(f"[{st['label']}]") + f"  {badge}")
        print(DIM(f"  {st['path']}"))
        if st["hooks"]:
            print(f"  hooks: {DIM(' · '.join(st['hooks']))}")
        print()

    # ── control plane ────────────────────────────────────────────────────────
    remote = RemotePolicySource()
    print(BOLD("CONTROL PLANE"))
    if not remote.configured:
        print(DIM("  not configured (PRIVACYHOOK_CONTROLPLANE_URL unset — using local policy.json only)"))
    else:
        rules = remote.refresh(ttl_seconds=0)
        cached = remote._load_cache()
        age = int(time.time() - cached.get("fetched_at", 0)) if cached else None
        if rules and age is not None and age <= 2:
            print(GREEN(f"  ✓ connected") + DIM(f"  {remote.url}  —  {len(rules)} rule(s), synced just now"))
        elif rules:
            print(YELLOW(f"  ⚠ cached") + DIM(f"  {remote.url}  —  {len(rules)} rule(s), server unreachable, using last known policy ({age}s old)"))
        else:
            print(RED(f"  ✗ unreachable") + DIM(f"  {remote.url}  —  no cached policy available"))
    print()

    # ── session ──────────────────────────────────────────────────────────────
    db = session_db_path()
    print(BOLD("SESSION") + f"  {DIM(str(db))}")
    s = SessionStore.open()
    try:
        toks = s.all_tokens()
        if toks:
            print(f"  {YELLOW(str(len(toks)))} value{'s' if len(toks) != 1 else ''} redacted this session")
            for cat, orig_preview, tok in toks[:5]:
                masked = orig_preview[:4] + "••••" if len(orig_preview) > 4 else "••••"
                print(DIM(f"    {tok}  ({cat})  →  privacyhook reveal '{tok}'"))
            if len(toks) > 5:
                print(DIM(f"    … and {len(toks)-5} more"))
        else:
            print(DIM("  no tokens this session"))
    except Exception:
        print(DIM("  (no session data)"))
    finally:
        s.close()

    # ── recent events ────────────────────────────────────────────────────────
    print()
    print(BOLD("RECENT EVENTS"))
    try:
        log = _open_log()
        entries = log.read_last(5)
        if entries:
            for e in entries:
                print(_fmt_event(e))
        else:
            print(DIM("  (none)"))
    except Exception as exc:
        print(DIM(f"  (no audit: {exc})"))
    print()
    return 0


def _open_log() -> AuditLog:
    from .hooks._common import _load_persistent_hmac_key
    return AuditLog(hmac_key=_load_persistent_hmac_key())


def cmd_reveal(args: argparse.Namespace) -> int:
    s = SessionStore.open()
    try:
        original = s.get_original(args.token)
    finally:
        s.close()
    if original is None:
        return _exit(f"token {args.token!r} not found in current session")
    print(original)
    return 0


def cmd_audit_follow(args: argparse.Namespace) -> int:
    log = _open_log()
    print(BOLD("SESSION AUDIT") + DIM("  —  live (Ctrl-C to stop)"))
    print("─" * 64)
    seen = len(log.read_all())
    try:
        while True:
            entries = log.read_all()
            for e in entries[seen:]:
                if args.json:
                    print(json.dumps(e))
                else:
                    print(_fmt_event(e))
            seen = len(entries)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        return 0


def cmd_audit(args: argparse.Namespace) -> int:
    if args.follow:
        return cmd_audit_follow(args)
    log = _open_log()
    entries = log.read_last(args.last) if args.last else log.read_all()

    if args.json:
        for e in entries:
            print(json.dumps(e))
        return 0

    # ── pretty output ────────────────────────────────────────────────────────
    n = len(entries)
    blocks  = sum(1 for e in entries if e.get("event") == "block")
    redacts = sum(1 for e in entries if e.get("event") == "redact")
    warns   = sum(1 for e in entries if e.get("event") == "warn")
    tokens_total = sum(e.get("count", 0) for e in entries if e.get("event") in ("redact", "warn"))

    print()
    print(BOLD(f"SESSION AUDIT") + DIM(f"  —  {n} event{'s' if n != 1 else ''}"))
    print("─" * 64)
    if not entries:
        print(DIM("  (no events recorded yet)"))
    else:
        for e in entries:
            print(_fmt_event(e))
    print("─" * 64)

    # summary line
    parts = []
    if blocks:
        parts.append(RED(f"{blocks} blocked"))
    if redacts:
        parts.append(YELLOW(f"{redacts} redacted"))
    if warns:
        parts.append(YELLOW(f"{warns} warned"))
    if tokens_total:
        parts.append(DIM(f"{tokens_total} values replaced with [WALL:*] tokens"))
    if parts:
        print("  " + "  ·  ".join(parts))

    # chain verify
    if args.verify or n > 0:
        ok, msg = log.verify()
        if ok:
            print("  " + GREEN("✓ chain intact"))
        else:
            print("  " + RED(f"✗ chain BROKEN: {msg}"))

    # reveal hint
    session_tokens: list[str] = []
    s = SessionStore.open()
    try:
        session_tokens = [tok for _, _, tok in s.all_tokens()][:3]
    except Exception:
        pass
    finally:
        s.close()
    if session_tokens:
        print()
        print(DIM("  Active tokens this session:"))
        for tok in session_tokens:
            print(DIM(f"    {tok}  →  privacyhook reveal '{tok}'"))

    print()
    return 0 if (not args.verify or log.verify()[0]) else 1


def _parse_date_bound(s: str | None, *, end_of_day: bool) -> float | None:
    if not s:
        return None
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.timestamp()


def cmd_audit_export(args: argparse.Namespace) -> int:
    log = _open_log()
    since = _parse_date_bound(args.since, end_of_day=False)
    until = _parse_date_bound(args.until, end_of_day=True)
    out_path = Path(args.out) if args.out else Path(
        f"privacyhook-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    n = log.export_csv(out_path, since=since, until=until)
    ok, msg = log.verify()
    status = GREEN("✓ chain intact") if ok else RED(f"✗ chain BROKEN: {msg}")
    print(f"exported {n} event{'s' if n != 1 else ''} → {out_path}")
    print(f"  {status}")
    return 0


def cmd_policy_list(args: argparse.Namespace) -> int:
    rules = PolicyEngine().list_rules()
    if not rules:
        print(DIM("  (no custom rules — WorkspaceGuard built-ins still apply)"))
        return 0
    print(BOLD(f"POLICY RULES") + DIM(f"  —  {len(rules)}"))
    print("─" * 64)
    for r in rules:
        action_color = RED if r.action == "block" else (YELLOW if r.action == "warn" else GREEN)
        print(f"  {BOLD(r.id)}  [{r.tool}]  {r.match_type}={r.pattern!r}  → {action_color(r.action)}"
              + (f"  ({r.reason})" if r.reason else ""))
    return 0


def cmd_policy_add(args: argparse.Namespace) -> int:
    engine = PolicyEngine()
    if any(r.id == args.id for r in engine.list_rules()):
        return _exit(f"rule id {args.id!r} already exists")
    try:
        rule = Rule(
            id=args.id, tool=args.tool, match_type=args.match_type,
            pattern=args.pattern, action=args.action, reason=args.reason,
        )
    except ValueError as exc:
        return _exit(str(exc))
    engine.add(rule)
    print(f"added rule {rule.id!r} → {rule.action} on [{rule.tool}] {rule.match_type}={rule.pattern!r}")
    return 0


def cmd_policy_remove(args: argparse.Namespace) -> int:
    if PolicyEngine().remove(args.id):
        print(f"removed rule {args.id!r}")
        return 0
    return _exit(f"rule id {args.id!r} not found")


def cmd_policy_test(args: argparse.Namespace) -> int:
    engine = PolicyEngine()
    if args.path:
        action, rule = engine.evaluate(args.tool, path_str=args.target)
    else:
        action, rule = engine.evaluate(args.tool, command=args.target)
    color = RED if action == "block" else (YELLOW if action == "warn" else GREEN)
    if rule:
        print(f"{color(action)}  (matched rule {rule.id!r}: {rule.reason or rule.pattern})")
    else:
        print(f"{color(action)}  (no rule matched)")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    from .monitor import serve
    serve(host=args.host, port=args.port, open_browser=args.open)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="privacyhook",
        description="Privacy-first security layer for Claude Code",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    cli_choices = SUPPORTED_CLIS + ["all", "auto"]

    install = sub.add_parser("install", help="register hooks in CLI settings file")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--yes", "-y", action="store_true")
    install.add_argument("--cli", default="auto", choices=cli_choices,
                         help="target CLI: claude, codex, gemini, all, auto (default: auto-detect)")
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall", help="remove privacyhook hooks")
    uninstall.add_argument("--yes", "-y", action="store_true")
    uninstall.add_argument("--cli", default="auto", choices=cli_choices)
    uninstall.set_defaults(func=cmd_uninstall)

    status = sub.add_parser("status", help="show hook + session status")
    status.add_argument("--cli", default="auto", choices=cli_choices)
    status.set_defaults(func=cmd_status)

    reveal = sub.add_parser("reveal", help="reveal original value for a token")
    reveal.add_argument("token")
    reveal.set_defaults(func=cmd_reveal)

    audit = sub.add_parser("audit", help="print audit log")
    audit.add_argument("--verify", action="store_true", help="verify HMAC chain")
    audit.add_argument("--last", type=int, default=0, help="show only last N entries")
    audit.add_argument("--json", action="store_true", help="raw JSONL output")
    audit.add_argument("--follow", "-f", action="store_true", help="watch for new events live")
    audit_sub = audit.add_subparsers(dest="audit_cmd")

    audit_export = audit_sub.add_parser("export", help="export audit log as CSV for compliance/audit review")
    audit_export.add_argument("--since", help="YYYY-MM-DD, inclusive")
    audit_export.add_argument("--until", help="YYYY-MM-DD, inclusive")
    audit_export.add_argument("--out", help="output path (default: privacyhook-audit-<timestamp>.csv)")
    audit_export.set_defaults(func=cmd_audit_export)

    audit.set_defaults(func=cmd_audit)

    policy = sub.add_parser("policy", help="manage custom tool-call policy rules")
    policy_sub = policy.add_subparsers(dest="policy_cmd", required=True)

    p_list = policy_sub.add_parser("list", help="list active rules")
    p_list.set_defaults(func=cmd_policy_list)

    p_add = policy_sub.add_parser("add", help="add a rule")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--tool", default="*", help="'*' or 'Bash'/'Read'/... ('|'-separated)")
    p_add.add_argument("--match", required=True, dest="pattern",
                        help="regex (command_regex) or glob (path_glob)")
    p_add.add_argument("--match-type", default="command_regex", choices=sorted(VALID_MATCH_TYPES))
    p_add.add_argument("--action", required=True, choices=sorted(VALID_ACTIONS))
    p_add.add_argument("--reason", default="")
    p_add.set_defaults(func=cmd_policy_add)

    p_rm = policy_sub.add_parser("remove", help="remove a rule by id")
    p_rm.add_argument("id")
    p_rm.set_defaults(func=cmd_policy_remove)

    p_test = policy_sub.add_parser("test", help="dry-run a command/path against current rules")
    p_test.add_argument("target")
    p_test.add_argument("--tool", default="Bash")
    p_test.add_argument("--path", action="store_true", help="treat target as a path, not a command")
    p_test.set_defaults(func=cmd_policy_test)

    monitor = sub.add_parser("monitor", help="serve a live audit-log UI on localhost")
    monitor.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1, local only)")
    monitor.add_argument("--port", type=int, default=8956)
    monitor.add_argument("--open", action="store_true", help="open the page in a browser")
    monitor.set_defaults(func=cmd_monitor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
