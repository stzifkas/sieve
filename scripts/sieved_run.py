#!/usr/bin/env python3
"""Run a subprocess and print agent-facing output for shell-tool runs.

Usage (from repo root, with deps installed):

    uv run python scripts/sieved_run.py -- pytest tests/ -q
    uv run python scripts/sieved_run.py --no-sieve -- pytest tests/ -q
    uv run python scripts/sieved_run.py --save-raw -- pytest tests/ -q
    SIEVE_SAVE_RAW=1 uv run python scripts/sieved_run.py -- pytest tests/

Exit code matches the child process so failures still propagate.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sieve import CompressSession
from sieve.core import ErrorSignature, RawExecution, TestResult
from sieve.session import FileSnapshot, SessionState
from sieve.stats import TokenStats


def _parse_argv(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if "--" not in argv:
        print(
            "usage: sieved_run.py [--no-sieve] [--save-raw] [--save-raw-dir DIR] -- <command> [args...]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    sep = argv.index("--")
    pre, post = argv[:sep], argv[sep + 1 :]
    if not post:
        print(
            "usage: sieved_run.py [--no-sieve] [--save-raw] [--save-raw-dir DIR] -- <command> [args...]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    p = argparse.ArgumentParser(prog="sieved_run.py", add_help=False)
    p.add_argument("--no-sieve", action="store_true")
    p.add_argument("--save-raw", action="store_true")
    p.add_argument("--save-raw-dir", default=".sieve/runs")
    p.add_argument("--session-file", default=".sieve/session.json")
    opts, rest = p.parse_known_args(pre)
    if rest:
        print(f"sieved_run.py: unknown arguments before --: {rest}", file=sys.stderr)
        raise SystemExit(2)

    env_save = os.environ.get("SIEVE_SAVE_RAW", "").lower() in ("1", "true", "yes")
    opts.save_raw = bool(opts.save_raw or env_save)
    env_save_raw_dir = os.environ.get("SIEVE_SAVE_RAW_DIR", "").strip()
    if env_save_raw_dir:
        opts.save_raw_dir = env_save_raw_dir
    env_session_file = os.environ.get("SIEVE_SESSION_FILE", "").strip()
    if env_session_file:
        opts.session_file = env_session_file
    env_no_sieve = os.environ.get("SIEVE_NO_SIEVE", "").lower() in ("1", "true", "yes")
    opts.no_sieve = bool(opts.no_sieve or env_no_sieve)
    return opts, post


def _maybe_save_raw(
    *,
    save_raw: bool,
    save_raw_dir: str,
    command_display: str,
    cmd_argv: list[str],
    proc: subprocess.CompletedProcess[str],
    raw_text: str,
    agent_text: str,
    parser: str,
    mode: str,
    delta_hit: bool,
    dedup_hit: bool,
) -> None:
    if not save_raw:
        return
    base_dir = Path(save_raw_dir)
    if not base_dir.is_absolute():
        base_dir = Path.cwd() / base_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = uuid.uuid4().hex[:8]
    stem = base_dir / f"{stamp}_{uid}"
    stem.with_suffix(".stdout.txt").write_text(proc.stdout)
    stem.with_suffix(".stderr.txt").write_text(proc.stderr)
    stem.with_suffix(".agent.txt").write_text(agent_text)
    meta = {
        "command": command_display,
        "argv": cmd_argv,
        "exit_code": proc.returncode,
        "cwd": str(Path.cwd()),
        "mode": mode,
        "parser": parser,
        "raw_chars": len(raw_text),
        "agent_chars": len(agent_text),
        "saved_chars": max(len(raw_text) - len(agent_text), 0),
        "delta_hit": delta_hit,
        "dedup_hit": dedup_hit,
    }
    stem.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _load_session_state(path: Path) -> SessionState:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return SessionState()
    except (OSError, json.JSONDecodeError):
        return SessionState()

    state = SessionState(track_stats=bool(data.get("track_stats", True)))
    state.turn = int(data.get("turn", 0))
    state.test_results = {
        item["id"]: TestResult(**item)
        for item in data.get("test_results", [])
        if isinstance(item, dict) and "id" in item
    }
    state.seen_errors = [
        ErrorSignature(**item)
        for item in data.get("seen_errors", [])
        if isinstance(item, dict)
    ]
    state.read_files = {
        file_path: FileSnapshot(**snapshot)
        for file_path, snapshot in data.get("read_files", {}).items()
        if isinstance(snapshot, dict)
    }
    token_stats = data.get("token_stats")
    if isinstance(token_stats, dict):
        state.token_stats = TokenStats(**token_stats)
    return state


def _save_session_state(path: Path, state: SessionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "turn": state.turn,
        "track_stats": state.track_stats,
        "test_results": [result.to_dict() for result in state.test_results.values()],
        "seen_errors": [dataclasses.asdict(item) for item in state.seen_errors],
        "read_files": {
            file_path: dataclasses.asdict(snapshot)
            for file_path, snapshot in state.read_files.items()
        },
        "token_stats": dataclasses.asdict(state.token_stats),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(path)


def _combined_output(proc: subprocess.CompletedProcess[str]) -> str:
    execution = RawExecution(
        command="",
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
    )
    return execution.combined_output


def _compress_passthrough(
    *,
    command_display: str,
    raw_text: str,
    exit_code: int,
) -> tuple[str, str, bool, bool]:
    del command_display
    del exit_code
    return raw_text, "passthrough", False, False


def _should_passthrough_pytest_error(
    *,
    command_display: str,
    raw_text: str,
    exit_code: int,
) -> bool:
    if exit_code == 0:
        return False
    lower_cmd = command_display.lower()
    if "pytest" not in lower_cmd:
        return False
    error_hints = (
        "ImportError while loading conftest",
        "ModuleNotFoundError:",
        "No module named ",
        "Traceback (most recent call last):",
        "collected 0 items / 1 error",
    )
    return any(hint in raw_text for hint in error_hints)


def main() -> None:
    opts, cmd_argv = _parse_argv(sys.argv[1:])
    command_display = " ".join(cmd_argv)
    proc = subprocess.run(cmd_argv, capture_output=True, text=True)
    raw_text = _combined_output(proc)

    if opts.no_sieve:
        agent_text, parser, delta_hit, dedup_hit = _compress_passthrough(
            command_display=command_display,
            raw_text=raw_text,
            exit_code=proc.returncode,
        )
    elif _should_passthrough_pytest_error(
        command_display=command_display,
        raw_text=raw_text,
        exit_code=proc.returncode,
    ):
        agent_text, parser, delta_hit, dedup_hit = _compress_passthrough(
            command_display=command_display,
            raw_text=raw_text,
            exit_code=proc.returncode,
        )
    else:
        session_path = _resolve_path(opts.session_file)
        session = CompressSession(session_state=_load_session_state(session_path))
        result = session.compress(
            command=command_display,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
        _save_session_state(session_path, session.state)
        agent_text = result.text
        parser = result.parsed.tool_type
        delta_hit = bool(result.compressed.metadata.get("delta_hit"))
        dedup_hit = bool(result.compressed.metadata.get("dedup_hit"))

    _maybe_save_raw(
        save_raw=opts.save_raw,
        save_raw_dir=opts.save_raw_dir,
        command_display=command_display,
        cmd_argv=cmd_argv,
        proc=proc,
        raw_text=raw_text,
        agent_text=agent_text,
        parser=parser,
        mode="baseline" if opts.no_sieve else "sieve",
        delta_hit=delta_hit,
        dedup_hit=dedup_hit,
    )
    sys.stdout.write(agent_text)
    if agent_text and not agent_text.endswith("\n"):
        sys.stdout.write("\n")
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
