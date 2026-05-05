from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sieve_command_rewrite import rewrite_shell_command


class RewriteTests(unittest.TestCase):
    def test_wraps_pytest(self) -> None:
        cmd = "pytest tests/ -q"
        out = rewrite_shell_command(cmd, REPO)
        self.assertIn("scripts/sieved_run.py", out)
        self.assertTrue(out.endswith(cmd))

    def test_no_double_wrap(self) -> None:
        inner = "pytest tests/"
        wrapped = rewrite_shell_command(inner, REPO)
        again = rewrite_shell_command(wrapped, REPO)
        self.assertEqual(again, wrapped)

    def test_respects_raw_hint(self) -> None:
        cmd = "pytest tests/ --raw output please"
        self.assertEqual(rewrite_shell_command(cmd, REPO), cmd)

    def test_preserves_env_assignments(self) -> None:
        cmd = "DJANGO_SETTINGS_MODULE=tests.settings pytest tests/"
        out = rewrite_shell_command(cmd, REPO)
        self.assertTrue(out.startswith("DJANGO_SETTINGS_MODULE=tests.settings "))
        self.assertIn("sieved_run.py", out)

    def test_wrapper_respects_env_config(self) -> None:
        cmd = "pytest tests/ -q"
        with patch.dict(
            os.environ,
            {
                "SIEVE_NO_SIEVE": "1",
                "SIEVE_SAVE_RAW": "1",
                "SIEVE_SAVE_RAW_DIR": "/tmp/sieve runs",
                "SIEVE_SESSION_FILE": "/tmp/sieve-session.json",
            },
            clear=False,
        ):
            out = rewrite_shell_command(cmd, REPO)

        self.assertIn("--no-sieve", out)
        self.assertIn("--save-raw", out)
        self.assertIn("--save-raw-dir '/tmp/sieve runs'", out)
        self.assertIn("--session-file /tmp/sieve-session.json", out)


if __name__ == "__main__":
    unittest.main()
