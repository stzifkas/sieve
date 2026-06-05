from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from sieve.cli.config import (
    _install_claude_hook,
    _install_cursor_hook,
    _remove_claude_hook,
    _remove_cursor_hook,
    _run_claude,
    _run_cursor,
)


class ClaudeHookEditingTests(unittest.TestCase):
    def test_install_into_empty_settings(self) -> None:
        out = _install_claude_hook({})
        self.assertEqual(
            out,
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "sieve-hook-claude"}],
                        }
                    ]
                }
            },
        )

    def test_install_is_idempotent(self) -> None:
        once = _install_claude_hook({})
        twice = _install_claude_hook(once)
        self.assertEqual(once, twice)

    def test_install_appends_alongside_existing_bash_matcher(self) -> None:
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "other-tool"}],
                    }
                ]
            }
        }
        out = _install_claude_hook(existing)
        commands = [h["command"] for h in out["hooks"]["PreToolUse"][0]["hooks"]]
        self.assertEqual(commands, ["other-tool", "sieve-hook-claude"])

    def test_uninstall_removes_legacy_path_too(self) -> None:
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 /old/.claude/hooks/sieve_bash_rewrite.py",
                            }
                        ],
                    }
                ]
            }
        }
        out = _remove_claude_hook(existing)
        self.assertNotIn("hooks", out)

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".claude" / "settings.json"
            args = Namespace(
                scope="project",
                project_path=tmp,
                write=False,
                uninstall=False,
                status=False,
            )
            rc = _run_claude(args)
            self.assertEqual(rc, 0)
            self.assertFalse(target.exists())

    def test_write_creates_file_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".claude" / "settings.json"
            target.parent.mkdir()
            target.write_text('{"existing": true}\n')

            args = Namespace(
                scope="project",
                project_path=tmp,
                write=True,
                uninstall=False,
                status=False,
            )
            _run_claude(args)
            data = json.loads(target.read_text())
            self.assertIn("hooks", data)
            self.assertTrue(target.with_suffix(".json.sieve.bak").exists())


class CursorHookEditingTests(unittest.TestCase):
    def test_install_and_uninstall_roundtrip(self) -> None:
        installed = _install_cursor_hook({})
        self.assertEqual(
            installed,
            {
                "hooks": {
                    "preToolUse": [
                        {"matcher": "Shell", "command": "sieve-hook-cursor"}
                    ]
                }
            },
        )
        removed = _remove_cursor_hook(installed)
        self.assertEqual(removed, {})

    def test_uninstall_dry_run_status_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(
                scope="project",
                project_path=tmp,
                write=False,
                uninstall=True,
                status=False,
            )
            self.assertEqual(_run_cursor(args), 0)


if __name__ == "__main__":
    unittest.main()
