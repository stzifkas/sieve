from __future__ import annotations

import unittest

from benchmarks.ci_repair_bench import (
    CIRepairRow,
    CIRepairStep,
    benchmark_rows,
    build_observation,
    extract_steps,
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
            "logs": [{"log": "2026-01-01T00:00:00.000Z ##[error] failed\n", "step_name": "build"}],
            "diff": "SHOULD NOT APPEAR",
        }
        obs = build_observation(row)
        self.assertIn("name: ci", obs)
        self.assertIn("failed", obs)
        self.assertNotIn("SHOULD NOT APPEAR", obs)

    def test_extract_steps_splits_run_blocks_and_normalizes_lines(self) -> None:
        steps = extract_steps(
            [
                {
                    "log": (
                        "2026-01-01T00:00:00.000Z ##[group]Run pip install mypy\n"
                        "2026-01-01T00:00:01.000Z stdout: Collecting mypy\n"
                        "2026-01-01T00:00:02.000Z ##[endgroup]\n"
                        "2026-01-01T00:00:03.000Z ##[group]Run mypy src/\n"
                        "2026-01-01T00:00:04.000Z src/app.py:3: error: bad  [arg-type]\n"
                        "2026-01-01T00:00:05.000Z Found 1 error in 1 file\n"
                    ),
                    "step_name": "type-checker",
                }
            ]
        )
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].command, "pip install mypy")
        self.assertEqual(steps[1].command, "mypy src/")
        self.assertIn("Collecting mypy", steps[0].normalized_log)
        self.assertIn("src/app.py:3: error: bad  [arg-type]", steps[1].normalized_log)
        self.assertNotIn("##[group]", steps[1].normalized_log)
        self.assertNotIn("2026-01-01T00:00:05.000Z", steps[1].normalized_log)

    def test_summarize_passthrough(self) -> None:
        rows = [
            CIRepairRow(
                instance_id="1",
                repo_label="o/r",
                workflow_name="wf",
                error_types=("Lint",),
                workflow="name: ci\n",
                steps=(
                    CIRepairStep(
                        name="lint",
                        command="ruff check src/",
                        raw_log="x" * 100,
                        normalized_log="x" * 100,
                    ),
                ),
            )
        ]
        results = benchmark_rows(rows, sieve=False)
        s = summarize(results)
        self.assertEqual(s["ratio"], 0.0)
        self.assertEqual(s["parser_coverage"], 0.0)
        self.assertEqual(s["steps"], 1)

    def test_benchmark_rows_routes_per_step_tools(self) -> None:
        rows = [
            CIRepairRow(
                instance_id="1",
                repo_label="o/r",
                workflow_name="wf",
                error_types=("Type Checking Error",),
                workflow="name: ci\n",
                steps=(
                    CIRepairStep(
                        name="type-check",
                        command="mypy src/",
                        raw_log=(
                            "src/app.py:3: error: bad  [arg-type]\n"
                            "Found 1 error in 1 file\n"
                        ),
                        normalized_log=(
                            "src/app.py:3: error: bad  [arg-type]\n"
                            "Found 1 error in 1 file\n"
                        ),
                    ),
                ),
            )
        ]
        results = benchmark_rows(rows, sieve=True)
        s = summarize(results)
        self.assertIn("mypy", s["parsers"])
        self.assertEqual(results[0].step_results[0].parser, "mypy")


if __name__ == "__main__":
    unittest.main()
