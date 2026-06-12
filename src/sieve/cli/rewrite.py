"""Deterministic rewrite of shell commands to run through ``sieve-run``.

Used by the Claude Code ``PreToolUse`` (Bash) and Cursor ``preToolUse`` (Shell)
hooks shipped in ``sieve.hooks``.
"""

from __future__ import annotations

import os
import re
import shlex

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

RAW_TOKEN_HINTS: tuple[str, ...] = ("--raw",)
RAW_COMMENT_HINT = "sieve:raw"

DEFAULT_RUN_BIN = "sieve-run"


def _run_bin_argv() -> list[str]:
    """Return the argv prefix that invokes the sieve runner.

    Override with ``SIEVE_RUN_BIN`` (whitespace-split via shlex) for editable
    installs or unusual environments. Default assumes ``sieve-run`` is on PATH.
    """
    override = os.environ.get("SIEVE_RUN_BIN", "").strip()
    if override:
        return shlex.split(override)
    return [DEFAULT_RUN_BIN]


def _wrapper_prefix() -> str:
    parts = list(_run_bin_argv())
    if os.environ.get("SIEVE_NO_SIEVE", "").lower() in ("1", "true", "yes"):
        parts.append("--no-sieve")
    if os.environ.get("SIEVE_SAVE_RAW", "").lower() in ("1", "true", "yes"):
        parts.append("--save-raw")
    save_raw_dir = os.environ.get("SIEVE_SAVE_RAW_DIR", "").strip()
    if save_raw_dir:
        parts.extend(["--save-raw-dir", save_raw_dir])
    session_file = os.environ.get("SIEVE_SESSION_FILE", "").strip()
    if session_file:
        parts.extend(["--session-file", session_file])
    parts.append("--")
    return " ".join(shlex.quote(p) if i > 0 else p for i, p in enumerate(parts))


def already_wrapped(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    pref = _wrapper_prefix()
    if stripped.startswith(pref):
        return True
    if stripped.startswith(DEFAULT_RUN_BIN + " "):
        return True
    if "sieve.cli.run" in stripped:
        return True
    return False


def _blocked_by_raw_hint(command: str) -> bool:
    try:
        tokens = [token.lower() for token in shlex.split(command)]
    except ValueError:
        tokens = command.lower().split()

    for index, token in enumerate(tokens):
        if token in RAW_TOKEN_HINTS:
            return True
        if token == "#" and tokens[index + 1 : index + 2] == [RAW_COMMENT_HINT]:
            return True
        if token == "#" + RAW_COMMENT_HINT:
            return True
    return False


def _rest_is_noisy(rest: str) -> bool:
    r = rest.strip()
    return any(r == p or r.startswith(p + " ") for p in NOISY_PREFIXES)


def rewrite_shell_command(command: str) -> str:
    """Return a rewritten command string, or the original if no rewrite applies."""
    stripped = command.strip()
    if not stripped:
        return command
    if already_wrapped(stripped):
        return command
    if _blocked_by_raw_hint(stripped):
        return command

    wrap = _wrapper_prefix()

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
