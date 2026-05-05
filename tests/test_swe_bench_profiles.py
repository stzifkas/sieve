from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.run_swe_bench_profiles import RunConfig, build_runner_command, main


class SweBenchProfilesTests(unittest.TestCase):
    def test_build_runner_command_includes_profile_specific_result_path(self) -> None:
        cfg = RunConfig(
            manifest=Path("/tmp/manifest.jsonl"),
            integration_dir=Path("/tmp/integration"),
            results_dir=Path("/tmp/results"),
            profile="sieve",
            model="composer-2",
            limit=3,
            resume=True,
            workspace_root=Path("/tmp/workspaces"),
            sieve_repo_root=Path("/tmp/sieve"),
            keep_workspaces=True,
        )

        cmd = build_runner_command(cfg)

        self.assertEqual(cmd[:3], ["npx", "tsx", "src/run.ts"])
        self.assertIn("/tmp/results/swe-bench-lite.sieve.jsonl", cmd)
        self.assertIn("--resume", cmd)
        self.assertIn("/tmp/workspaces", cmd)
        self.assertIn("/tmp/sieve", cmd)
        self.assertIn("--keep-workspaces", cmd)

    def test_compare_only_mode_renders_report_from_existing_results(self) -> None:
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "swe_bench_compare"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "manifest.jsonl").write_text(
                '{"instance_id":"i","repo":"owner/repo","base_commit":"abc","problem_statement":"bug"}\n'
            )
            results_dir = tmp / "artifacts"
            results_dir.mkdir()
            (results_dir / "swe-bench-lite.baseline.jsonl").write_text(
                (fixture_dir / "baseline.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (results_dir / "swe-bench-lite.sieve.jsonl").write_text(
                (fixture_dir / "sieve.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(
                    [
                        "--manifest",
                        str(tmp / "manifest.jsonl"),
                        "--integration-dir",
                        str(Path(__file__).resolve().parents[1] / "integrations" / "swe-bench-lite-cursor"),
                        "--results-dir",
                        str(results_dir),
                        "--mode",
                        "compare-only",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["resolved_delta"], 1)


if __name__ == "__main__":
    unittest.main()
