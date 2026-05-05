#!/usr/bin/env python3
"""Claude Code PreToolUse hook: rewrite Bash tool commands through sieved_run.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from sieve_command_rewrite import rewrite_shell_command


def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name") or data.get("toolName") or ""
    if tool_name not in ("Bash", "bash", "Shell"):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }
            )
        )
        return

    tool_input = dict(data.get("tool_input") or data.get("toolInput") or {})
    command = tool_input.get("command") or ""
    new_command = rewrite_shell_command(command, ROOT)

    if new_command == command:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }
            )
        )
        return

    tool_input["command"] = new_command
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "Wrapped noisy CLI with Sieve.",
                    "updatedInput": tool_input,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
