from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.run_codex_swe_bench_profiles import (
    RUNNER_SIGNATURE,
    RunArtifacts,
    _result_matches_current_runner,
    build_codex_command,
    enrich_manifest_rows,
    extract_patch,
    main,
)
from scripts.setup_codex_swe_bench_experiment import HARNESS_CONTAINER, LOCAL_HOST_CLONE, ManifestRow
from scripts.setup_codex_swe_bench_experiment import build_layouts


class RunCodexSweBenchProfilesTests(unittest.TestCase):
    def test_build_codex_command_uses_json_and_workspace_write(self) -> None:
        layout = build_layouts(Path("/tmp/exp"))["sieve"]
        artifacts = RunArtifacts(
            events_jsonl=Path("/tmp/events.jsonl"),
            stderr_log=Path("/tmp/stderr.log"),
            final_message=Path("/tmp/final.md"),
            diff_patch=Path("/tmp/diff.patch"),
        )

        cmd = build_codex_command(
            layout=layout,
            artifacts=artifacts,
            model="codex-mini-latest",
            sandbox="workspace-write",
            ephemeral=True,
        )

        self.assertIn("--json", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("workspace-write", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertEqual(cmd[-1], "-")

    def test_extract_patch_excludes_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            subprocess_run = __import__("subprocess").run
            git = ["git", "-c", "core.excludesFile=/dev/null"]
            subprocess_run([*git, "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "tracked.txt").write_text("old\n", encoding="utf-8")
            subprocess_run([*git, "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess_run(
                [
                    *git,
                    "-c",
                    "user.name=Test User",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "init",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo / "tracked.txt").write_text("new\n", encoding="utf-8")
            (repo / "CODEX_PROMPT.txt").write_text("prompt\n", encoding="utf-8")

            patch = extract_patch(repo)

        self.assertIn("tracked.txt", patch)
        self.assertNotIn("CODEX_PROMPT.txt", patch)

    def test_compare_only_mode_renders_existing_results(self) -> None:
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "swe_bench_compare"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "manifest.jsonl"
            manifest.write_text(
                '{"instance_id":"i","repo":"owner/repo","base_commit":"abc","problem_statement":"bug"}\n',
                encoding="utf-8",
            )
            results = tmp / "artifacts"
            results.mkdir()
            (results / "codex-swe-bench-lite.baseline.jsonl").write_text(
                (fixture_dir / "baseline.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (results / "codex-swe-bench-lite.sieve.jsonl").write_text(
                (fixture_dir / "sieve.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(
                    [
                        "--manifest",
                        str(manifest),
                        "--results-dir",
                        str(results),
                        "--engine",
                        "codex",
                        "--mode",
                        "compare-only",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["resolved_delta"], 1)

    def test_resume_only_accepts_rows_from_current_runner_signature(self) -> None:
        self.assertTrue(
            _result_matches_current_runner(
                {
                    "instance_id": "i",
                    "environment_mode": HARNESS_CONTAINER,
                    "runner_signature": RUNNER_SIGNATURE,
                },
                HARNESS_CONTAINER,
            )
        )
        self.assertFalse(_result_matches_current_runner({"instance_id": "i"}, HARNESS_CONTAINER))
        self.assertFalse(
            _result_matches_current_runner(
                {
                    "instance_id": "i",
                    "environment_mode": HARNESS_CONTAINER,
                    "runner_signature": "old",
                }
                ,
                HARNESS_CONTAINER,
            )
        )
        self.assertFalse(
            _result_matches_current_runner(
                {
                    "instance_id": "i",
                    "environment_mode": LOCAL_HOST_CLONE,
                    "runner_signature": RUNNER_SIGNATURE,
                },
                HARNESS_CONTAINER,
            )
        )

    def test_enrich_manifest_rows_fills_missing_harness_fields_once(self) -> None:
        rows = [
            ManifestRow(
                instance_id="i",
                repo="owner/repo",
                base_commit="abc",
                problem_statement="bug",
                extra={},
            )
        ]
        dataset_rows = [
            {
                "instance_id": "i",
                "version": "1.0",
                "test_patch": "diff --git a/t b/t",
                "FAIL_TO_PASS": "[]",
                "PASS_TO_PASS": "[]",
                "environment_setup_commit": "def",
            }
        ]

        with patch("datasets.load_dataset", return_value=dataset_rows) as mocked:
            enriched = enrich_manifest_rows(rows, dataset="d", split="s")

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(enriched[0].extra["version"], "1.0")
        self.assertEqual(enriched[0].extra["environment_setup_commit"], "def")


if __name__ == "__main__":
    unittest.main()
