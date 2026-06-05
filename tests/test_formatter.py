from __future__ import annotations

import json
import unittest

from sieve import CompressSession
from sieve.config import OutputFormat
from sieve.core import CompressedOutput, DiagnosticItem, Severity, Status
from sieve.formatter import Formatter


def _sample(content: str = "line1\nline2", *, status: Status = Status.FAILURE) -> CompressedOutput:
    return CompressedOutput(
        tool_type="pytest",
        status=status,
        summary="1 failed, 2 passed",
        content=content,
        items=[
            DiagnosticItem(
                severity=Severity.ERROR,
                file="a.py",
                line=3,
                column=None,
                code="E001",
                message="bad <thing> & stuff",
                tool="mypy",
            )
        ],
        raw_chars=200,
        compressed_chars=len(content),
    )


class FormatterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = Formatter()

    def test_plain_returns_content_unchanged(self) -> None:
        out = _sample()
        self.assertEqual(self.formatter.format(out, OutputFormat.PLAIN), out.content)

    def test_structured_is_valid_json_with_expected_keys(self) -> None:
        payload = json.loads(self.formatter.format(_sample(), OutputFormat.STRUCTURED))
        self.assertEqual(payload["tool"], "pytest")
        self.assertEqual(payload["status"], "failure")
        self.assertEqual(payload["summary"], "1 failed, 2 passed")
        self.assertEqual(payload["content"], "line1\nline2")
        self.assertEqual(len(payload["items"]), 1)
        self.assertTrue(payload["compression"].endswith("%"))

    def test_xml_escapes_special_characters(self) -> None:
        xml = self.formatter.format(_sample(), OutputFormat.XML)
        self.assertIn('tool="pytest"', xml)
        self.assertIn('status="failure"', xml)
        self.assertIn("<summary>1 failed, 2 passed</summary>", xml)
        # The diagnostic message must be entity-escaped, not raw.
        self.assertIn("bad &lt;thing&gt; &amp; stuff", xml)
        self.assertNotIn("bad <thing> & stuff", xml)

    def test_minimal_success_returns_summary_only(self) -> None:
        out = _sample(content="whatever", status=Status.SUCCESS)
        self.assertEqual(self.formatter.format(out, OutputFormat.MINIMAL), out.summary)

    def test_minimal_failure_returns_item_lines(self) -> None:
        out = _sample(status=Status.FAILURE)
        self.assertEqual(
            self.formatter.format(out, OutputFormat.MINIMAL),
            out.items[0].compressed_repr,
        )


class InvariantByFormatTests(unittest.TestCase):
    """The never-larger-than-raw guard applies to plain output; the structured
    and xml envelopes may exceed raw on tiny inputs (documented tradeoff)."""

    def test_plain_never_exceeds_raw_on_tiny_input(self) -> None:
        raw = "hi"
        result = CompressSession().compress(command="echo hi", stdout=raw + "\n")
        self.assertLessEqual(len(result.text), len(raw))

    def test_structured_envelope_may_exceed_raw_but_is_valid_json(self) -> None:
        raw = "hi"
        result = CompressSession().compress(
            command="echo hi",
            stdout=raw + "\n",
            output_format=OutputFormat.STRUCTURED,
        )
        # Valid JSON regardless of size...
        json.loads(result.text)
        # ...and on a 2-char input the envelope is necessarily larger.
        self.assertGreater(len(result.text), len(raw))


if __name__ == "__main__":
    unittest.main()
