from __future__ import annotations

import unittest
from pathlib import Path

from benchmarks.swe_bench_lite import benchmark_steps, load_trajectory_steps, summarize


FIXTURES = Path(__file__).parent / "fixtures" / "swe_bench_lite"


class SweBenchLiteBenchmarkTests(unittest.TestCase):
    def test_loads_observation_steps_from_traj_files(self) -> None:
        steps = load_trajectory_steps(FIXTURES)

        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0].instance_id, "demo_instance")
        self.assertEqual(steps[-1].instance_id, "generic_instance")

    def test_benchmark_preserves_session_per_instance(self) -> None:
        steps = load_trajectory_steps(FIXTURES)
        results = benchmark_steps(steps)

        self.assertEqual(results[0].parser, "pytest")
        self.assertEqual(results[1].parser, "pytest")
        self.assertFalse(results[0].delta_hit)
        self.assertTrue(results[1].delta_hit)
        self.assertEqual(results[2].parser, "python_traceback")
        self.assertEqual(results[3].parser, "generic")

    def test_summary_reports_parser_coverage(self) -> None:
        summary = summarize(benchmark_steps(load_trajectory_steps(FIXTURES)))

        self.assertEqual(summary["instances"], 2)
        self.assertEqual(summary["steps"], 4)
        self.assertAlmostEqual(summary["parser_coverage"], 0.75)
        self.assertAlmostEqual(summary["delta_hit_rate"], 0.25)
        self.assertIn("pytest", summary["parsers"])
        self.assertIn("generic", summary["parsers"])


if __name__ == "__main__":
    unittest.main()
