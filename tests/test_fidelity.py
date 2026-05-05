"""Round-trip fidelity tests.

Compression is only useful if the facts an agent needs to act on survive into
the compressed text. For each fixture we assert that the load-bearing
identifiers (nodeids, file paths, line numbers, expected/actual values, error
types) are all present in the final formatted output.

These tests are independent of how the compressor frames the output — they
just check that the key strings end up in the result.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from sieve import CompressSession, OutputFormat


FIXTURES = Path(__file__).parent / "fixtures"


def compress(
    *,
    command: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int,
    output_format: OutputFormat = OutputFormat.PLAIN,
) -> str:
    return CompressSession().compress(
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        output_format=output_format,
    ).text


def load(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text()


class PytestFidelity(unittest.TestCase):
    def test_two_failures_preserves_nodeids_files_lines_and_diff(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "two_failures.txt"),
            exit_code=1,
        )
        # Both failing nodeids
        self.assertIn("test_user_update", text)
        self.assertIn("test_user_delete", text)
        # Files and lines
        self.assertIn("test_views.py", text)
        self.assertIn("89", text)
        self.assertIn("102", text)
        # Expected vs actual on at least one failure
        self.assertIn("403", text)
        self.assertIn("200", text)
        # Counts
        self.assertIn("2 failed", text)
        self.assertIn("140 passed", text)

    def test_large_verbose_preserves_all_failures(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "large_verbose.txt"),
            exit_code=1,
        )
        for nodeid in (
            "test_user_update",
            "test_user_delete",
            "test_user_permissions",
            "test_query_by_title",
        ):
            self.assertIn(nodeid, text, f"missing nodeid {nodeid!r} in compressed output")
        self.assertIn("4 failed", text)
        self.assertIn("183 passed", text)

    def test_collection_error_preserves_module_and_line(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "collection_error.txt"),
            exit_code=2,
        )
        self.assertIn("test_imports.py", text)
        self.assertIn("ModuleNotFoundError", text)
        self.assertIn("app.missing", text)

    def test_setup_error_preserves_fixture_name(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "setup_error.txt"),
            exit_code=1,
        )
        self.assertIn("test_create_user", text)
        self.assertIn("fixture 'db' not found", text)

    def test_all_passed_summary_survives(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "all_passed.txt"),
            exit_code=0,
        )
        self.assertIn("3 passed", text)


class RuntimeFidelity(unittest.TestCase):
    def test_python_type_error_preserves_location_and_chain(self) -> None:
        text = compress(
            command="python app.py",
            stderr=load("runtime", "python_type_error.txt"),
            exit_code=1,
        )
        self.assertIn("TypeError", text)
        self.assertIn("api/views.py", text)
        self.assertIn("67", text)

    def test_chained_exception_preserves_both_layers(self) -> None:
        text = compress(
            command="python app.py",
            stderr=load("runtime", "chained_exception.txt"),
            exit_code=1,
        )
        self.assertIn("RuntimeError", text)
        # Underlying ValueError must surface as related context
        self.assertIn("ValueError", text)

    def test_exception_group_preserves_constituent_errors(self) -> None:
        text = compress(
            command="python app.py",
            stderr=load("runtime", "exception_group.txt"),
            exit_code=1,
        )
        self.assertIn("ExceptionGroup", text)
        self.assertIn("ValueError", text)
        self.assertIn("TypeError", text)

    def test_syntax_error_preserves_file_line_and_pointer(self) -> None:
        text = compress(
            command="python bad.py",
            stderr=load("runtime", "syntax_error.txt"),
            exit_code=1,
        )
        self.assertIn("SyntaxError", text)
        self.assertIn("bad.py", text)
        self.assertIn("3", text)

    def test_deep_django_traceback_preserves_user_frame(self) -> None:
        text = compress(
            command="python manage.py runserver",
            stderr=load("runtime", "deep_django_traceback.txt"),
            exit_code=1,
        )
        self.assertIn("AttributeError", text)
        # The actionable frame is in user code, not framework code
        self.assertIn("api/views.py", text)
        self.assertIn("tenant", text)


class DiagnosticFidelity(unittest.TestCase):
    def test_mypy_preserves_files_lines_codes(self) -> None:
        text = compress(
            command="mypy src/",
            stdout=load("mypy", "with_errors.txt"),
            exit_code=1,
        )
        self.assertIn("api.py", text)
        self.assertIn("23", text)
        self.assertIn("arg-type", text)
        self.assertIn("return-value", text)
        self.assertIn("union-attr", text)
        self.assertIn("var-annotated", text)
        self.assertIn("Found 4 errors", text)

    def test_tsc_pretty_preserves_codes_and_locations(self) -> None:
        text = compress(
            command="npx tsc --noEmit",
            stderr=load("tsc", "pretty_errors.txt"),
            exit_code=1,
        )
        for ts_code in ("TS2345", "TS2322", "TS2769"):
            self.assertIn(ts_code, text)
        self.assertIn("Form.tsx", text)
        self.assertIn("12", text)
        self.assertIn("Found 3 errors", text)

    def test_eslint_preserves_rule_ids_and_files(self) -> None:
        text = compress(
            command="npx eslint src/",
            stdout=load("eslint", "with_errors.txt"),
            exit_code=1,
        )
        for rule in (
            "react/react-in-jsx-scope",
            "no-unused-vars",
            "eqeqeq",
            "no-undef",
            "quotes",
            "indent",
        ):
            self.assertIn(rule, text)
        self.assertIn("Button.jsx", text)
        self.assertIn("8 problems", text)

    def test_gcc_preserves_file_line_col_and_drops_source_context(self) -> None:
        text = compress(
            command="gcc -c src/parser.c",
            stderr=load("gcc", "parse_error.txt"),
            exit_code=1,
        )
        self.assertIn("parser.c", text)
        self.assertIn("147", text)
        self.assertIn("212", text)
        self.assertIn("undeclared", text)
        # The source-context line "147 |     node->left = parse_term();"
        # must NOT survive — it's noise, not signal.
        self.assertNotIn("|     node->left", text)

    def test_pip_failure_preserves_actionable_summary(self) -> None:
        text = compress(
            command="pip install -r requirements.txt",
            stdout=load("pip", "install_failure.txt"),
            exit_code=1,
        )
        self.assertIn("psycopg2", text)
        self.assertIn("PIP FAIL", text)

    def test_pip_success_collapses_to_count(self) -> None:
        text = compress(
            command="pip install -r requirements.txt",
            stdout=load("pip", "install_success.txt"),
            exit_code=0,
        )
        self.assertIn("PIP", text)
        self.assertIn("installed", text)
        # Detailed download URLs must NOT survive
        self.assertNotIn("Downloading", text)


class FormatFidelity(unittest.TestCase):
    """Key facts must survive across all output formats."""

    def test_xml_format_preserves_failure_facts(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "two_failures.txt"),
            exit_code=1,
            output_format=OutputFormat.XML,
        )
        self.assertIn("test_user_update", text)
        self.assertIn("test_user_delete", text)
        self.assertIn("403", text)

    def test_structured_format_preserves_failure_facts(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "two_failures.txt"),
            exit_code=1,
            output_format=OutputFormat.STRUCTURED,
        )
        self.assertIn("test_user_update", text)
        self.assertIn("\"line\": 89", text)
        self.assertIn("\"actual\": \"403\"", text)
        self.assertIn("\"expected\": \"200\"", text)

    def test_minimal_format_keeps_error_items(self) -> None:
        text = compress(
            command="pytest tests/",
            stdout=load("pytest", "two_failures.txt"),
            exit_code=1,
            output_format=OutputFormat.MINIMAL,
        )
        self.assertIn("test_user_update", text)
        self.assertIn("test_user_delete", text)


class DeltaFidelity(unittest.TestCase):
    def test_delta_resolution_preserves_resolved_nodeid(self) -> None:
        session = CompressSession()
        session.compress(
            command="pytest tests/",
            stdout=load("pytest", "two_failures.txt"),
            exit_code=1,
        )
        second = session.compress(
            command="pytest tests/",
            stdout=load("pytest", "one_failure.txt"),
            exit_code=1,
        )
        # Resolved test must be named explicitly
        self.assertIn("test_user_update", second.text)
        self.assertIn("now passes", second.text)
        # Remaining failure must still be visible with file:line
        self.assertIn("test_user_delete", second.text)
        self.assertIn("102", second.text)

    def test_delta_unchanged_run_still_names_failing_tests(self) -> None:
        session = CompressSession()
        raw = load("pytest", "two_failures.txt")
        session.compress(command="pytest tests/", stdout=raw, exit_code=1)
        second = session.compress(command="pytest tests/", stdout=raw, exit_code=1)
        self.assertIn("test_user_update", second.text)
        self.assertIn("test_user_delete", second.text)


if __name__ == "__main__":
    unittest.main()
