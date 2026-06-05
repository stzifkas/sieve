"""Cursor Agent ``preToolUse`` hook: rewrite Shell commands through ``sieve-run``."""

from __future__ import annotations

import json
import sys

from sieve.cli.rewrite import rewrite_shell_command


def main(argv: list[str] | None = None) -> int:
    del argv
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Shell":
        json.dump({"permission": "allow"}, sys.stdout)
        return 0

    tool_input = dict(data.get("tool_input") or {})
    command = tool_input.get("command") or ""
    new_command = rewrite_shell_command(command)

    if new_command == command:
        json.dump({"permission": "allow"}, sys.stdout)
        return 0

    tool_input["command"] = new_command
    json.dump(
        {
            "permission": "allow",
            "updated_input": tool_input,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
