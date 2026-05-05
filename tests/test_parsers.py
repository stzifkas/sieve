from __future__ import annotations

import unittest
from pathlib import Path

from sieve.config import CompressConfig
from sieve.core import RawExecution, Severity, Status
from sieve.parsers.eslint_ import EslintParser
from sieve.parsers.gcc import GccParser
from sieve.parsers.generic import GenericParser
from sieve.parsers.mypy_ import MypyParser
from sieve.parsers.pip_ import PipParser
from sieve.parsers.pytest_ import PytestParser
from sieve.parsers.python_tb import PythonTracebackParser
from sieve.parsers.tsc import TscParser


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text()


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CompressConfig()

    def test_pytest_parser_handles_all_passed_run(self) -> None:
        raw = load_fixture("pytest", "all_passed.txt")
        parser = PytestParser(self.config)
        parsed = parser.parse(
            RawExecution(command="pytest tests/", stdout=raw, exit_code=0)
        )

        self.assertEqual(parsed.status, Status.SUCCESS)
        self.assertEqual(parsed.summary, "3 passed (3 total)")
        self.assertEqual(parsed.items, [])

    def test_pytest_parser_extracts_failures(self) -> None:
        raw = load_fixture("pytest", "two_failures.txt")
        parser = PytestParser(self.config)
        parsed = parser.parse(
            RawExecution(command="pytest tests/", stdout=raw, exit_code=1)
        )

        self.assertEqual(parsed.status, Status.FAILURE)
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].file, "tests/test_views.py")
        self.assertEqual(parsed.items[0].line, 89)
        self.assertEqual(parsed.items[0].actual, "403")
        self.assertEqual(parsed.items[0].expected, "200")
        self.assertEqual(parsed.summary, "2 failed, 140 passed (142 total)")
        self.assertEqual(parsed.metadata["pattern_hint"], "All failures return 403 in test_views.py")

    def test_pytest_parser_handles_collection_error(self) -> None:
        raw = load_fixture("pytest", "collection_error.txt")
        parser = PytestParser(self.config)
        parsed = parser.parse(
            RawExecution(command="pytest tests/", stdout=raw, exit_code=2)
        )

        self.assertEqual(parsed.status, Status.ERROR)
        self.assertEqual(len(parsed.items), 1)
        item = parsed.items[0]
        self.assertEqual(item.status, "error")
        self.assertEqual(item.file, "tests/test_imports.py")
        self.assertEqual(item.line, 3)
        self.assertEqual(item.message, "ModuleNotFoundError: No module named 'app.missing'")
        self.assertEqual(parsed.summary, "1 error")

    def test_pytest_parser_handles_setup_error(self) -> None:
        raw = load_fixture("pytest", "setup_error.txt")
        parser = PytestParser(self.config)
        parsed = parser.parse(
            RawExecution(command="pytest tests/", stdout=raw, exit_code=1)
        )

        self.assertEqual(parsed.status, Status.ERROR)
        self.assertEqual(len(parsed.items), 1)
        item = parsed.items[0]
        self.assertEqual(item.status, "error")
        self.assertEqual(item.id, "tests/test_api.py::test_create_user")
        self.assertEqual(item.file, "/workspace/tests/test_api.py")
        self.assertEqual(item.line, 12)
        self.assertEqual(item.message, "fixture 'db' not found")
        self.assertEqual(parsed.summary, "1 error, 2 passed (3 total)")

    def test_pytest_parser_handles_quiet_parameterized_failure(self) -> None:
        raw = load_fixture("pytest", "quiet_param_failure.txt")
        parser = PytestParser(self.config)
        parsed = parser.parse(
            RawExecution(command="python -m pytest -q", stdout=raw, exit_code=1)
        )

        self.assertEqual(parsed.status, Status.FAILURE)
        self.assertEqual(len(parsed.items), 1)
        item = parsed.items[0]
        self.assertEqual(item.id, "tests/test_math.py::test_sum[param-case]")
        self.assertEqual(item.actual, "3")
        self.assertEqual(item.expected, "4")
        self.assertEqual(parsed.summary, "1 failed, 2 passed (3 total)")

    def test_python_traceback_parser_extracts_primary_frame(self) -> None:
        raw = load_fixture("runtime", "python_type_error.txt")
        parser = PythonTracebackParser(self.config)
        parsed = parser.parse(RawExecution(command="python app.py", stderr=raw, exit_code=1))

        self.assertEqual(parsed.status, Status.ERROR)
        self.assertEqual(len(parsed.items), 1)
        item = parsed.items[0]
        self.assertEqual(item.error_type, "TypeError")
        self.assertEqual(item.file, "api/views.py")
        self.assertEqual(item.line, 67)
        self.assertEqual(item.call_chain[-1], "views.py:67")

    def test_python_traceback_parser_handles_chained_exception(self) -> None:
        raw = load_fixture("runtime", "chained_exception.txt")
        parser = PythonTracebackParser(self.config)
        parsed = parser.parse(RawExecution(command="python app.py", stderr=raw, exit_code=1))

        self.assertEqual(parsed.status, Status.ERROR)
        item = parsed.items[0]
        self.assertEqual(item.error_type, "RuntimeError")
        self.assertEqual(item.file, "/workspace/app.py")
        self.assertEqual(item.line, 9)
        self.assertIn("ValueError: invalid literal for int() with base 10: 'abc'", parsed.metadata["related_exceptions"])

    def test_python_traceback_parser_handles_syntax_error(self) -> None:
        raw = load_fixture("runtime", "syntax_error.txt")
        parser = PythonTracebackParser(self.config)
        parsed = parser.parse(RawExecution(command="python bad.py", stderr=raw, exit_code=1))

        self.assertEqual(parsed.status, Status.ERROR)
        item = parsed.items[0]
        self.assertEqual(item.error_type, "SyntaxError")
        self.assertEqual(item.file, "/workspace/bad.py")
        self.assertEqual(item.line, 3)
        self.assertEqual(parsed.metadata["source_context"], ["def broken(:", "^"])

    def test_python_traceback_parser_handles_bare_exception_line(self) -> None:
        raw = load_fixture("runtime", "bare_module_not_found.txt")
        parser = PythonTracebackParser(self.config)
        parsed = parser.parse(RawExecution(command="python -c ...", stderr=raw, exit_code=1))

        self.assertEqual(parsed.status, Status.ERROR)
        item = parsed.items[0]
        self.assertEqual(item.error_type, "ModuleNotFoundError")
        self.assertEqual(item.file, "<unknown>")
        self.assertEqual(parsed.summary, "ModuleNotFoundError: No module named 'yaml'")

    def test_python_traceback_parser_handles_exception_group(self) -> None:
        raw = load_fixture("runtime", "exception_group.txt")
        parser = PythonTracebackParser(self.config)
        parsed = parser.parse(RawExecution(command="python app.py", stderr=raw, exit_code=1))

        self.assertEqual(parsed.status, Status.ERROR)
        item = parsed.items[0]
        self.assertEqual(item.error_type, "ExceptionGroup")
        self.assertEqual(item.file, "/workspace/app.py")
        self.assertEqual(item.line, 6)
        self.assertIn("ValueError: bad", parsed.metadata["related_exceptions"])
        self.assertIn("TypeError: worse", parsed.metadata["related_exceptions"])

    def test_mypy_parser_extracts_errors_and_attaches_notes(self) -> None:
        raw = load_fixture("mypy", "with_errors.txt")
        parsed = MypyParser(self.config).parse(
            RawExecution(command="mypy src/", stdout=raw, exit_code=1)
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        # 4 errors + 1 warning = 5 items
        self.assertEqual(len(parsed.items), 5)
        first = parsed.items[0]
        self.assertEqual(first.severity, Severity.ERROR)
        self.assertEqual(first.file, "src/sieve/api.py")
        self.assertEqual(first.line, 23)
        self.assertEqual(first.code, "arg-type")
        # Note from same file:line should attach to the error above it
        self.assertEqual(len(first.related), 1)
        self.assertIn("Did you mean", first.related[0])
        # Column-bearing form is preserved
        last = parsed.items[-1]
        self.assertEqual(last.line, 67)
        self.assertEqual(last.column, 5)
        self.assertIn("Found 4 errors in 4 files", parsed.summary)

    def test_mypy_parser_handles_clean_run(self) -> None:
        raw = load_fixture("mypy", "clean.txt")
        parsed = MypyParser(self.config).parse(
            RawExecution(command="mypy src/", stdout=raw, exit_code=0)
        )
        self.assertEqual(parsed.status, Status.SUCCESS)
        self.assertEqual(parsed.items, [])
        self.assertIn("Success", parsed.summary)

    def test_tsc_parser_handles_pretty_format(self) -> None:
        raw = load_fixture("tsc", "pretty_errors.txt")
        parsed = TscParser(self.config).parse(
            RawExecution(command="npx tsc --noEmit", stderr=raw, exit_code=1)
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        # 3 errors + 1 warning
        self.assertEqual(len(parsed.items), 4)
        first = parsed.items[0]
        self.assertEqual(first.file, "src/components/Form.tsx")
        self.assertEqual(first.line, 12)
        self.assertEqual(first.column, 5)
        self.assertEqual(first.code, "TS2345")
        self.assertEqual(parsed.items[-1].severity, Severity.WARNING)
        self.assertIn("Found 3 errors", parsed.summary)

    def test_tsc_parser_handles_legacy_format(self) -> None:
        raw = load_fixture("tsc", "legacy_errors.txt")
        parsed = TscParser(self.config).parse(
            RawExecution(command="tsc", stderr=raw, exit_code=1)
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        self.assertEqual(len(parsed.items), 3)
        self.assertEqual(parsed.items[0].column, 5)
        self.assertEqual(parsed.items[2].code, "TS2769")

    def test_eslint_parser_extracts_diagnostics_per_file(self) -> None:
        raw = load_fixture("eslint", "with_errors.txt")
        parsed = EslintParser(self.config).parse(
            RawExecution(command="npx eslint src/", stdout=raw, exit_code=1)
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        self.assertEqual(len(parsed.items), 8)
        self.assertEqual(parsed.items[0].file, "/workspace/src/components/Button.jsx")
        self.assertEqual(parsed.items[0].code, "react/react-in-jsx-scope")
        # Severity discrimination
        warnings = [i for i in parsed.items if i.severity == Severity.WARNING]
        self.assertEqual(len(warnings), 2)
        self.assertIn("8 problems", parsed.summary)

    def test_gcc_parser_strips_source_context_and_groups_notes(self) -> None:
        raw = load_fixture("gcc", "parse_error.txt")
        parsed = GccParser(self.config).parse(
            RawExecution(command="gcc -c src/parser.c", stderr=raw, exit_code=1)
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        # 3 errors + 1 warning, notes attached to errors not separate items
        errors = [i for i in parsed.items if i.severity == Severity.ERROR]
        warnings = [i for i in parsed.items if i.severity == Severity.WARNING]
        self.assertEqual(len(errors), 3)
        self.assertEqual(len(warnings), 1)
        # First error attaches the 'expected ... but argument' note
        self.assertEqual(errors[0].file, "src/parser.c")
        self.assertEqual(errors[0].line, 147)
        self.assertEqual(errors[0].column, 23)
        self.assertGreaterEqual(len(errors[0].related), 1)
        # Source-context lines (with "147 |") must NOT appear as items
        self.assertTrue(all(i.line is not None for i in parsed.items))

    def test_pip_parser_summarizes_install_failure(self) -> None:
        raw = load_fixture("pip", "install_failure.txt")
        parsed = PipParser(self.config).parse(
            RawExecution(
                command="pip install -r requirements.txt", stdout=raw, exit_code=1
            )
        )
        self.assertEqual(parsed.status, Status.FAILURE)
        self.assertIn("psycopg2", parsed.summary)
        self.assertTrue(parsed.summary.startswith("PIP FAIL:"))
        # The detail block should still be retained as a TextOutputItem
        self.assertEqual(len(parsed.items), 1)

    def test_generic_parser_truncates_long_output(self) -> None:
        raw = load_fixture("generic", "long_output.txt")
        parser = GenericParser(self.config)
        parsed = parser.parse(RawExecution(command="tail -f log.txt", stdout=raw, exit_code=0))

        self.assertEqual(parsed.status, Status.SUCCESS)
        display_lines = parsed.metadata["display_lines"]
        self.assertLessEqual(len(display_lines), self.config.max_raw_lines)
        self.assertIn("[previous line repeated", "\n".join(display_lines))
        self.assertTrue(parsed.summary.startswith("Output: 60 lines ->"))


if __name__ == "__main__":
    unittest.main()
