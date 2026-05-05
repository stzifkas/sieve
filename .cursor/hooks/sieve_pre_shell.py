#!/usr/bin/env python3
"""Cursor Agent hook: rewrite Shell tool commands through sieved_run.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from sieve_command_rewrite import rewrite_shell_command


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Shell":
        print(json.dumps({"permission": "allow"}))
        return

    tool_input = dict(data.get("tool_input") or {})
    command = tool_input.get("command") or ""
    new_command = rewrite_shell_command(command, ROOT)

    if new_command == command:
        print(json.dumps({"permission": "allow"}))
        return

    tool_input["command"] = new_command
    print(
        json.dumps(
            {
                "permission": "allow",
                "updated_input": tool_input,
            }
        )
    )


if __name__ == "__main__":
    main()
