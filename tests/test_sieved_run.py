from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sieved_run import (
    _load_session_state,
    _parse_argv,
    _save_session_state,
    _should_passthrough_pytest_error,
)
from sieve import CompressSession


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text()


class SievedRunSessionTests(unittest.TestCase):
    def test_persistent_session_state_enables_delta_across_sessions(self) -> None:
        raw = load_fixture("pytest", "two_failures.txt")
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session.json"

            first_session = CompressSession(session_state=_load_session_state(session_path))
            first = first_session.compress(
                command="pytest tests/",
                stdout=raw,
                exit_code=1,
            )
            _save_session_state(session_path, first_session.state)

            second_session = CompressSession(
                session_state=_load_session_state(session_path)
            )
            second = second_session.compress(
                command="pytest tests/",
                stdout=raw,
                exit_code=1,
            )

        self.assertIn("PYTEST: 2 failed, 140 passed (142 total)", first.text)
        self.assertIn("PYTEST DELTA: unchanged", second.text)

    def test_corrupt_session_file_falls_back_to_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session.json"
            session_path.write_text("{not json")

            session = _load_session_state(session_path)

        self.assertEqual(session.turn, 0)
        self.assertEqual(session.test_results, {})

    def test_parse_argv_honors_no_sieve_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "captures"
            session_file = Path(tmpdir) / "session.json"
            old_env = dict(os.environ)
            try:
                os.environ["SIEVE_NO_SIEVE"] = "1"
                os.environ["SIEVE_SAVE_RAW_DIR"] = str(save_dir)
                os.environ["SIEVE_SESSION_FILE"] = str(session_file)
                opts, post = _parse_argv(["--", "pytest", "tests/"])
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(opts.no_sieve)
        self.assertEqual(opts.save_raw_dir, str(save_dir))
        self.assertEqual(opts.session_file, str(session_file))
        self.assertEqual(post, ["pytest", "tests/"])

    def test_saved_session_round_trip_preserves_stats(self) -> None:
        raw = load_fixture("pytest", "two_failures.txt")
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session.json"

            session = CompressSession(session_state=_load_session_state(session_path))
            session.compress(command="pytest tests/", stdout=raw, exit_code=1)
            _save_session_state(session_path, session.state)

            payload = json.loads(session_path.read_text())

        self.assertEqual(payload["turn"], 1)
        self.assertEqual(payload["token_stats"]["turns_processed"], 1)

    def test_pytest_import_error_passes_through_raw(self) -> None:
        raw = (
            "ImportError while loading conftest '/tmp/proj/conftest.py'.\n"
            "conftest.py:9: in <module>\n"
            "    import hypothesis\n"
            "E   ModuleNotFoundError: No module named 'hypothesis'\n"
        )

        self.assertTrue(
            _should_passthrough_pytest_error(
                command_display="pytest tests/test_x.py -q",
                raw_text=raw,
                exit_code=4,
            )
        )


if __name__ == "__main__":
    unittest.main()
