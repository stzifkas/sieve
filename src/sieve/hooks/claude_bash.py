"""Claude Code ``PreToolUse`` hook: rewrite Bash commands through ``sieve-run``.

Wired up via ``settings.json``::

    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "Bash",
            "hooks": [
              {"type": "command", "command": "sieve-hook-claude"}
            ]
          }
        ]
      }
    }
"""

from __future__ import annotations

import json
import sys

from sieve.cli.rewrite import rewrite_shell_command


def main(argv: list[str] | None = None) -> int:
    del argv
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name") or data.get("toolName") or ""
    if tool_name not in ("Bash", "bash", "Shell"):
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            },
            sys.stdout,
        )
        return 0

    tool_input = dict(data.get("tool_input") or data.get("toolInput") or {})
    command = tool_input.get("command") or ""
    new_command = rewrite_shell_command(command)

    if new_command == command:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            },
            sys.stdout,
        )
        return 0

    tool_input["command"] = new_command
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Wrapped noisy CLI with Sieve.",
                "updatedInput": tool_input,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
