"""Configure agent harness integrations.

Exposes ``sieve config claude`` and ``sieve config cursor``, which install
(or remove) Sieve hooks in the relevant settings file. By default the command
prints a preview and the target path; pass ``--write`` to actually mutate.
"""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

CLAUDE_HOOK_COMMAND = "sieve-hook-claude"
CURSOR_HOOK_COMMAND = "sieve-hook-cursor"


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="agent", required=True)

    p_claude = sub.add_parser("claude", help="Install hook into Claude Code settings.json.")
    _add_common_flags(p_claude)
    p_claude.set_defaults(handler=lambda args: _run_claude(args))

    p_cursor = sub.add_parser("cursor", help="Install hook into Cursor hooks.json.")
    _add_common_flags(p_cursor)
    p_cursor.set_defaults(handler=lambda args: _run_cursor(args))


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--scope",
        choices=("user", "project"),
        default="user",
        help="user (~/.claude or ~/.cursor) or project (./.claude or ./.cursor). Default: user.",
    )
    p.add_argument(
        "--project-path",
        default=".",
        help="Project root when --scope project. Default: current directory.",
    )
    p.add_argument("--write", action="store_true", help="Mutate the settings file.")
    p.add_argument("--uninstall", action="store_true", help="Remove the Sieve hook.")
    p.add_argument("--status", action="store_true", help="Print current hook status and exit.")


# ---------------------------------------------------------------------------
# Claude Code

def _claude_settings_path(args: argparse.Namespace) -> Path:
    if args.scope == "user":
        return Path.home() / ".claude" / "settings.json"
    return Path(args.project_path).resolve() / ".claude" / "settings.json"


def _run_claude(args: argparse.Namespace) -> int:
    target = _claude_settings_path(args)

    if args.status:
        return _print_claude_status(target)

    current = _read_json(target)
    if args.uninstall:
        updated = _remove_claude_hook(current)
        action = "uninstall"
    else:
        updated = _install_claude_hook(current)
        action = "install"

    return _apply(target, current, updated, args.write, agent="claude", action=action)


def _install_claude_hook(settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(settings)
    hooks = out.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])

    for entry in pre:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher") != "Bash":
            continue
        sub = entry.setdefault("hooks", [])
        if any(_is_sieve_claude_hook(h) for h in sub):
            return out
        sub.append({"type": "command", "command": CLAUDE_HOOK_COMMAND})
        return out

    pre.append(
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": CLAUDE_HOOK_COMMAND}],
        }
    )
    return out


def _remove_claude_hook(settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    pre = hooks.get("PreToolUse")
    if not isinstance(pre, list):
        return out

    cleaned_pre: list[dict[str, Any]] = []
    for entry in pre:
        if not isinstance(entry, dict) or entry.get("matcher") != "Bash":
            cleaned_pre.append(entry)
            continue
        sub = [h for h in entry.get("hooks", []) if not _is_sieve_claude_hook(h)]
        if sub:
            new_entry = dict(entry)
            new_entry["hooks"] = sub
            cleaned_pre.append(new_entry)
    if cleaned_pre:
        hooks["PreToolUse"] = cleaned_pre
    else:
        hooks.pop("PreToolUse", None)
    if not hooks:
        out.pop("hooks", None)
    return out


def _is_sieve_claude_hook(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    cmd = str(entry.get("command", ""))
    if not cmd:
        return False
    return (
        cmd == CLAUDE_HOOK_COMMAND
        or "sieve-hook-claude" in cmd
        or "sieve.hooks.claude_bash" in cmd
        or "sieve_bash_rewrite.py" in cmd  # legacy in-repo path
    )


def _print_claude_status(target: Path) -> int:
    settings = _read_json(target)
    pre = (settings.get("hooks") or {}).get("PreToolUse") or []
    found: list[str] = []
    for entry in pre:
        if not isinstance(entry, dict) or entry.get("matcher") != "Bash":
            continue
        for hook in entry.get("hooks", []) or []:
            if _is_sieve_claude_hook(hook):
                found.append(str(hook.get("command", "")))
    print(f"settings: {target}")
    if not target.exists():
        print("  (file does not exist)")
    if found:
        for cmd in found:
            print(f"  installed: {cmd}")
    else:
        print("  not installed")
    return 0


# ---------------------------------------------------------------------------
# Cursor

def _cursor_settings_path(args: argparse.Namespace) -> Path:
    if args.scope == "user":
        return Path.home() / ".cursor" / "hooks.json"
    return Path(args.project_path).resolve() / ".cursor" / "hooks.json"


def _run_cursor(args: argparse.Namespace) -> int:
    target = _cursor_settings_path(args)

    if args.status:
        return _print_cursor_status(target)

    current = _read_json(target)
    if args.uninstall:
        updated = _remove_cursor_hook(current)
        action = "uninstall"
    else:
        updated = _install_cursor_hook(current)
        action = "install"

    return _apply(target, current, updated, args.write, agent="cursor", action=action)


def _install_cursor_hook(settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(settings)
    hooks = out.setdefault("hooks", {})
    pre = hooks.setdefault("preToolUse", [])
    if any(_is_sieve_cursor_hook(h) for h in pre):
        return out
    pre.append({"matcher": "Shell", "command": CURSOR_HOOK_COMMAND})
    return out


def _remove_cursor_hook(settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    pre = hooks.get("preToolUse")
    if not isinstance(pre, list):
        return out
    cleaned = [h for h in pre if not _is_sieve_cursor_hook(h)]
    if cleaned:
        hooks["preToolUse"] = cleaned
    else:
        hooks.pop("preToolUse", None)
    if not hooks:
        out.pop("hooks", None)
    return out


def _is_sieve_cursor_hook(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    cmd = str(entry.get("command", ""))
    return (
        cmd == CURSOR_HOOK_COMMAND
        or "sieve-hook-cursor" in cmd
        or "sieve.hooks.cursor_shell" in cmd
        or "sieve_pre_shell.py" in cmd  # legacy in-repo path
    )


def _print_cursor_status(target: Path) -> int:
    settings = _read_json(target)
    pre = (settings.get("hooks") or {}).get("preToolUse") or []
    found = [str(h.get("command", "")) for h in pre if _is_sieve_cursor_hook(h)]
    print(f"settings: {target}")
    if not target.exists():
        print("  (file does not exist)")
    if found:
        for cmd in found:
            print(f"  installed: {cmd}")
    else:
        print("  not installed")
    return 0


# ---------------------------------------------------------------------------
# Shared

def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"sieve config: {path} is not valid JSON ({exc})")
    if not isinstance(data, dict):
        raise SystemExit(f"sieve config: expected JSON object at {path}")
    return data


def _apply(
    target: Path,
    current: dict[str, Any],
    updated: dict[str, Any],
    write: bool,
    *,
    agent: str,
    action: str,
) -> int:
    if updated == current:
        print(f"sieve config {agent}: nothing to do (already {action}ed).")
        print(f"  target: {target}")
        return 0

    rendered = json.dumps(updated, indent=2) + "\n"

    if not write:
        print(f"sieve config {agent} ({action}) — DRY RUN. Pass --write to apply.")
        print(f"  target: {target}")
        print()
        print(rendered, end="")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(target.suffix + ".sieve.bak")
        shutil.copy2(target, backup)
        print(f"  backup: {backup}")
    target.write_text(rendered)
    print(f"sieve config {agent}: {action}ed.")
    print(f"  target: {target}")
    return 0
