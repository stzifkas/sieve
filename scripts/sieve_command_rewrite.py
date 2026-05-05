"""Deterministic rewrite of shell commands to run through scripts/sieved_run.py.

Used by Cursor `preToolUse` (Shell) and Claude Code `PreToolUse` (Bash) hooks.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

# Commands whose stdout/stderr usually bloat agent context.
NOISY_PREFIXES: tuple[str, ...] = (
    "pytest",
    "python -m pytest",
    "pdm run pytest",
    "poetry run pytest",
    "mypy",
    "python -m mypy",
    "tsc",
    "npx tsc",
    "eslint",
    "npx eslint",
    "ruff check",
    "pip install",
    "pip3 install",
    "uv pip install",
    "python -m pip install",
)

RAW_HINTS: tuple[str, ...] = (
    "--raw",
    " verbatim",
    "full log",
    "full logs",
)


def _wrapper_prefix(repo_root: Path) -> str:
    """Prefix that works even when Shell cwd is another repo (SWE-bench checkouts)."""
    sr = repo_root.resolve()
    parts = [
        "uv",
        "run",
        "--directory",
        shlex.quote(str(sr)),
        "python",
        shlex.quote(str(sr / "scripts" / "sieved_run.py")),
    ]
    if os.environ.get("SIEVE_NO_SIEVE", "").lower() in ("1", "true", "yes"):
        parts.append("--no-sieve")
    if os.environ.get("SIEVE_SAVE_RAW", "").lower() in ("1", "true", "yes"):
        parts.append("--save-raw")
    save_raw_dir = os.environ.get("SIEVE_SAVE_RAW_DIR", "").strip()
    if save_raw_dir:
        parts.extend(["--save-raw-dir", shlex.quote(save_raw_dir)])
    session_file = os.environ.get("SIEVE_SESSION_FILE", "").strip()
    if session_file:
        parts.extend(["--session-file", shlex.quote(session_file)])
    parts.append("--")
    return " ".join(parts)


def already_wrapped(command: str, repo_root: Path) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    pref = _wrapper_prefix(repo_root)
    if stripped.startswith(pref):
        return True
    return "scripts/sieved_run.py" in stripped


def _blocked_by_raw_hint(command: str) -> bool:
    lower = command.lower()
    return any(h in lower for h in RAW_HINTS)


def _rest_is_noisy(rest: str) -> bool:
    r = rest.strip()
    return any(r == p or r.startswith(p + " ") for p in NOISY_PREFIXES)


def rewrite_shell_command(command: str, repo_root: Path) -> str:
    """Return a new command string, or the original if no rewrite applies."""
    stripped = command.strip()
    if not stripped:
        return command
    if already_wrapped(stripped, repo_root):
        return command
    if _blocked_by_raw_hint(stripped):
        return command

    wrap = _wrapper_prefix(repo_root)

    match = re.match(r"^((?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)+)(.+)$", stripped)
    if match:
        env_part, rest = match.groups()
        rest_s = rest.strip()
        if _rest_is_noisy(rest_s):
            return f"{env_part}{wrap} {rest_s}"
        return command

    if _rest_is_noisy(stripped):
        return f"{wrap} {stripped}"

    return command
