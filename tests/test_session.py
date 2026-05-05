from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
