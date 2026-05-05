from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from benchmarks.swe_bench_compare import compare_rows, load_rows, main


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "swe_bench_compare"


class SweBenchCompareTests(unittest.TestCase):
    def test_compare_rows_reports_resolve_and_context_delta(self) -> None:
        report = compare_rows(
            load_rows(FIXTURE_DIR / "baseline.jsonl"),
            load_rows(FIXTURE_DIR / "sieve.jsonl"),
        )

        self.assertEqual(report["instances_compared"], 2)
        self.assertEqual(report["baseline"]["resolved"], 1)
        self.assertEqual(report["sieve"]["resolved"], 2)
        self.assertEqual(report["resolved_delta"], 1)
        self.assertEqual(report["saved_char_delta"], 1100)
        self.assertEqual(report["patch_delta"], 1)
        self.assertEqual(report["paired_outcomes"]["improved"], 1)

    def test_cli_json_output(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(
                [
                    "--baseline",
                    str(FIXTURE_DIR / "baseline.jsonl"),
                    "--sieve",
                    str(FIXTURE_DIR / "sieve.jsonl"),
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["resolved_delta"], 1)

    def test_compare_rows_treats_unscored_resolved_as_unknown(self) -> None:
        report = compare_rows(
            [
                {"instance_id": "i", "resolved": None, "model_patch": "diff --git a/x b/x\n", "context": {}},
            ],
            [
                {"instance_id": "i", "resolved": None, "model_patch": "diff --git a/x b/x\n", "context": {}},
            ],
        )

        self.assertEqual(report["baseline"]["resolved"], 0)
        self.assertEqual(report["baseline"]["resolved_known"], 0)
        self.assertEqual(report["baseline"]["resolved_unknown"], 1)
        self.assertIsNone(report["baseline"]["resolve_rate"])
        self.assertEqual(report["paired_outcomes"]["unknown"], 1)
        self.assertIsNone(report["rows"][0]["baseline_resolved"])


if __name__ == "__main__":
    unittest.main()
