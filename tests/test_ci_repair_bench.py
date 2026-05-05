from __future__ import annotations

import unittest

from benchmarks.ci_repair_bench import (
    CIRepairRow,
    benchmark_rows,
    build_observation,
    flatten_logs,
    summarize,
)


class CIRepairBenchTests(unittest.TestCase):
    def test_flatten_logs_handles_steps(self) -> None:
        blob = flatten_logs(
            [
                {"log": "err A", "step_name": "lint"},
                {"log": "err B", "setp_name": "tests"},  # dataset typo field
            ]
        )
        self.assertIn("lint", blob)
        self.assertIn("err A", blob)
        self.assertIn("err B", blob)

    def test_build_observation_no_diff_leak(self) -> None:
        row = {
            "workflow": "name: ci\non: push\n",
            "logs": [{"log": "##[error] failed\n", "step_name": "build"}],
            "diff": "SHOULD NOT APPEAR",
        }
        obs = build_observation(row)
        self.assertIn("name: ci", obs)
        self.assertIn("##[error]", obs)
        self.assertNotIn("SHOULD NOT APPEAR", obs)

    def test_summarize_passthrough(self) -> None:
        rows = [
            CIRepairRow(
                instance_id="1",
                repo_label="o/r",
                workflow_name="wf",
                error_types=("Lint",),
                observation="x" * 100,
            )
        ]
        results = benchmark_rows(rows, sieve=False)
        s = summarize(results)
        self.assertEqual(s["ratio"], 0.0)
        self.assertEqual(s["parser_coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
