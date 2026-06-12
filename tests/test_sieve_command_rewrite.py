from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sieve.cli.rewrite import rewrite_shell_command


class RewriteTests(unittest.TestCase):
    def test_wraps_pytest(self) -> None:
        cmd = "pytest tests/ -q"
        out = rewrite_shell_command(cmd)
        self.assertIn("sieve-run", out)
        self.assertTrue(out.endswith(cmd))

    def test_no_double_wrap(self) -> None:
        inner = "pytest tests/"
        wrapped = rewrite_shell_command(inner)
        again = rewrite_shell_command(wrapped)
        self.assertEqual(again, wrapped)

    def test_respects_raw_hint(self) -> None:
        for cmd in (
            "pytest tests/ --raw output please",
            "pytest tests/ # sieve:raw",
            "pytest tests/ #sieve:raw",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(rewrite_shell_command(cmd), cmd)

    def test_raw_hint_falls_back_to_whitespace_split(self) -> None:
        cmd = "pytest tests/ --raw 'unterminated"
        self.assertEqual(rewrite_shell_command(cmd), cmd)

    def test_raw_hint_requires_exact_raw_flag(self) -> None:
        for cmd in (
            "pytest --raw-data tests/",
            "pytest tests/test_raw.py --rawX",
        ):
            with self.subTest(cmd=cmd):
                out = rewrite_shell_command(cmd)
                self.assertIn("sieve-run", out)
                self.assertTrue(out.endswith(cmd))

    def test_text_raw_hints_require_whole_arguments(self) -> None:
        for cmd in (
            "pytest tests/verbatim_case.py",
            "pytest 'tests/full logs/test_example.py'",
            "pytest -k verbatim",
            "pytest -k 'full log'",
        ):
            with self.subTest(cmd=cmd):
                out = rewrite_shell_command(cmd)
                self.assertIn("sieve-run", out)
                self.assertTrue(out.endswith(cmd))

    def test_preserves_env_assignments(self) -> None:
        cmd = "DJANGO_SETTINGS_MODULE=tests.settings pytest tests/"
        out = rewrite_shell_command(cmd)
        self.assertTrue(out.startswith("DJANGO_SETTINGS_MODULE=tests.settings "))
        self.assertIn("sieve-run", out)

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
            out = rewrite_shell_command(cmd)

        self.assertIn("--no-sieve", out)
        self.assertIn("--save-raw", out)
        self.assertIn("--save-raw-dir '/tmp/sieve runs'", out)
        self.assertIn("--session-file /tmp/sieve-session.json", out)

    def test_run_bin_override(self) -> None:
        cmd = "pytest tests/ -q"
        with patch.dict(
            os.environ,
            {"SIEVE_RUN_BIN": "python3 -m sieve.cli.run"},
            clear=False,
        ):
            out = rewrite_shell_command(cmd)

        self.assertIn("python3 -m sieve.cli.run", out)
        self.assertNotIn("sieve-run --", out)


if __name__ == "__main__":
    unittest.main()
