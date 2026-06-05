from __future__ import annotations

import unittest
from unittest.mock import patch

from sieve import CompressSession
from sieve.core import TestResult
from sieve.session import SessionState


class SessionStateTests(unittest.TestCase):
    def test_get_test_delta_marks_resolved_failures(self) -> None:
        session = SessionState()
        first = TestResult(
            id="tests/test_views.py::test_user_update",
            status="failed",
            file="tests/test_views.py",
            line=89,
            actual="403",
            expected="200",
        )
        second = TestResult(
            id="tests/test_views.py::test_user_delete",
            status="failed",
            file="tests/test_views.py",
            line=102,
            actual="403",
            expected="204",
        )

        initial = session.get_test_delta([first, second])
        self.assertEqual(len(initial.new_failures), 2)

        next_delta = session.get_test_delta([second])
        self.assertEqual(len(next_delta.resolved_failures), 1)
        self.assertEqual(next_delta.resolved_failures[0][0].id, first.id)
        self.assertEqual(len(next_delta.unchanged_failures), 1)


class PassthroughSessionStateTests(unittest.TestCase):
    def test_parser_failure_still_advances_turn_and_records_stats(self) -> None:
        # passthrough_on_error defaults True: a parser exception must return
        # raw output *and* leave session state consistent with the happy path,
        # so later turns compute deltas against the right turn number.
        session = CompressSession()
        raw = "boom output that failed to parse"
        with patch.object(session.router, "parse", side_effect=RuntimeError("parser blew up")):
            result = session.compress(command="pytest tests/", stdout=raw, exit_code=1)

        self.assertEqual(result.text, raw)
        self.assertEqual(session.state.turn, 1)
        self.assertEqual(session.state.token_stats.turns_processed, 1)
        self.assertEqual(session.state.token_stats.total_raw_chars, len(raw))


if __name__ == "__main__":
    unittest.main()
