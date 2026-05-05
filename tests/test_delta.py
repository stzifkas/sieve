from __future__ import annotations

import unittest
from pathlib import Path

from sieve import CompressSession


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text()


class DeltaEngineTests(unittest.TestCase):
    def test_pytest_delta_reports_resolved_failure(self) -> None:
        session = CompressSession()
        first = session.compress(
            command="pytest tests/",
            stdout=load_fixture("pytest", "two_failures.txt"),
            exit_code=1,
        )
        second = session.compress(
            command="pytest tests/",
            stdout=load_fixture("pytest", "one_failure.txt"),
            exit_code=1,
        )

        self.assertIn("PYTEST: 2 failed, 140 passed (142 total)", first.text)
        self.assertIn(
            "PASS tests/test_views.py::TestUserViewSet::test_user_update now passes",
            second.text,
        )
        self.assertIn(
            "STILL FAIL tests/test_views.py::TestUserViewSet::test_user_delete",
            second.text,
        )

    def test_runtime_delta_deduplicates_repeated_traceback(self) -> None:
        session = CompressSession()
        raw = load_fixture("runtime", "python_type_error.txt")
        first = session.compress(command="python app.py", stderr=raw, exit_code=1)
        second = session.compress(command="python app.py", stderr=raw, exit_code=1)

        self.assertIn("RUNTIME ERROR: TypeError in api/views.py:67", first.text)
        self.assertIn("RUNTIME DELTA: same error as turn 1", second.text)


if __name__ == "__main__":
    unittest.main()
