from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from benchmarks.swe_bench_lite import benchmark_steps, load_trajectory_steps, main


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "swe_bench_lite"


class SweBenchLiteCliTests(unittest.TestCase):
    def test_compare_exit_zero(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--traj-dir", str(FIXTURE_DIR), "--compare"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("sieve off", out)
        self.assertIn("sieve on", out)

    def test_compare_json_delta_chars(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--traj-dir", str(FIXTURE_DIR), "--compare", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("baseline", payload)
        self.assertIn("sieve", payload)
        self.assertIn("delta_chars", payload)
        self.assertGreater(payload["delta_chars"], 0)

    def test_benchmark_passthrough_matches_raw(self) -> None:
        steps = load_trajectory_steps(FIXTURE_DIR)
        results = benchmark_steps(steps, sieve=False)
        for r in results:
            self.assertEqual(r.parser, "passthrough")
            self.assertEqual(r.raw_chars, r.compressed_chars)


if __name__ == "__main__":
    unittest.main()
