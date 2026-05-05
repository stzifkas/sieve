from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.swe_bench_harness_results import (
    find_summary_report,
    load_resolved_ids,
    merge_resolved_into_jsonl,
)


class SweBenchHarnessResultsTests(unittest.TestCase):
    def test_merge_resolved_into_jsonl_updates_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            predictions = tmp / "predictions.jsonl"
            predictions.write_text(
                "\n".join(
                    [
                        json.dumps({"instance_id": "a", "resolved": False, "model_patch": "x"}),
                        json.dumps({"instance_id": "b", "resolved": False, "model_patch": "y"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary = tmp / "cursor-sdk-baseline.test-run.json"
            summary.write_text(
                json.dumps({"resolved_ids": ["b"]}),
                encoding="utf-8",
            )

            merge_resolved_into_jsonl(
                predictions_path=predictions,
                resolved_ids=load_resolved_ids(summary),
                summary_report=summary,
                run_id="test-run",
            )

            rows = [json.loads(line) for line in predictions.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(rows[0]["resolved"])
            self.assertTrue(rows[1]["resolved"])
            self.assertEqual(rows[1]["harness"]["status"], "scored")
            self.assertEqual(rows[1]["harness"]["run_id"], "test-run")

    def test_find_summary_report_matches_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            wanted = tmp / "cursor-sdk-baseline.run-123.json"
            wanted.write_text("{}", encoding="utf-8")
            (tmp / "other.json").write_text("{}", encoding="utf-8")

            self.assertEqual(find_summary_report(report_dir=tmp, run_id="run-123"), wanted)


if __name__ == "__main__":
    unittest.main()
