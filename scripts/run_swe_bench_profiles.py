#!/usr/bin/env python3
"""Run SWE-bench Lite Cursor experiments with sieve off/on and compare the results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from benchmarks.swe_bench_compare import compare_rows, load_rows, render_text
from scripts.swe_bench_harness_results import (
    load_resolved_ids,
    merge_resolved_into_jsonl,
    run_harness,
)


@dataclass(frozen=True)
class RunConfig:
    manifest: Path
    integration_dir: Path
    results_dir: Path
    profile: str
    model: str
    limit: int
    resume: bool
    workspace_root: Path | None
    sieve_repo_root: Path | None
    keep_workspaces: bool


def _profile_results_path(results_dir: Path, profile: str) -> Path:
    return results_dir / f"swe-bench-lite.{profile}.jsonl"


def build_runner_command(cfg: RunConfig) -> list[str]:
    cmd = [
        "npx",
        "tsx",
        "src/run.ts",
        "--manifest",
        str(cfg.manifest),
        "--predictions",
        str(_profile_results_path(cfg.results_dir, cfg.profile)),
        "--profile",
        cfg.profile,
        "--model",
        cfg.model,
    ]
    if cfg.limit > 0:
        cmd.extend(["--limit", str(cfg.limit)])
    if cfg.resume:
        cmd.append("--resume")
    if cfg.workspace_root is not None:
        cmd.extend(["--workspace-root", str(cfg.workspace_root)])
    if cfg.sieve_repo_root is not None:
        cmd.extend(["--sieve-repo-root", str(cfg.sieve_repo_root)])
    if cfg.keep_workspaces:
        cmd.append("--keep-workspaces")
    return cmd


def run_profile(cfg: RunConfig, *, env: dict[str, str] | None = None) -> int:
    proc = subprocess.run(
        build_runner_command(cfg),
        cwd=cfg.integration_dir,
        env=env,
    )
    return proc.returncode


def compare_profile_outputs(results_dir: Path) -> dict[str, Any]:
    baseline_path = _profile_results_path(results_dir, "baseline")
    sieve_path = _profile_results_path(results_dir, "sieve")
    return compare_rows(load_rows(baseline_path), load_rows(sieve_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--integration-dir",
        type=Path,
        default=ROOT / "integrations" / "swe-bench-lite-cursor",
    )
    parser.add_argument("--results-dir", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--sieve-repo-root", type=Path)
    parser.add_argument("--model", default="composer-2")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument("--eval-with-harness", action="store_true")
    parser.add_argument(
        "--harness-dataset",
        default="princeton-nlp/SWE-bench_Lite",
        help="Dataset passed to the official SWE-bench harness.",
    )
    parser.add_argument("--harness-split", default="test")
    parser.add_argument("--harness-max-workers", type=int, default=4)
    parser.add_argument(
        "--harness-report-dir",
        type=Path,
        default=ROOT / "artifacts" / "harness-reports",
    )
    parser.add_argument(
        "--mode",
        choices=("run", "compare-only"),
        default="run",
        help="Run both profiles then compare, or only compare existing JSONL outputs.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        print(f"missing manifest: {args.manifest}", file=sys.stderr)
        return 2
    if not args.integration_dir.is_dir():
        print(f"missing integration dir: {args.integration_dir}", file=sys.stderr)
        return 2

    args.results_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "run":
        env = dict(os.environ)
        if "CURSOR_API_KEY" not in env:
            print("missing CURSOR_API_KEY", file=sys.stderr)
            return 2

        run_root = args.workspace_root
        for profile in ("baseline", "sieve"):
            cfg = RunConfig(
                manifest=args.manifest.resolve(),
                integration_dir=args.integration_dir.resolve(),
                results_dir=args.results_dir.resolve(),
                profile=profile,
                model=args.model,
                limit=args.limit,
                resume=args.resume,
                workspace_root=run_root.resolve() if run_root else None,
                sieve_repo_root=args.sieve_repo_root.resolve()
                if args.sieve_repo_root
                else None,
                keep_workspaces=args.keep_workspaces,
            )
            code = run_profile(cfg, env=env)
            if code != 0:
                return code

    if args.eval_with_harness:
        for profile in ("baseline", "sieve"):
            predictions_path = _profile_results_path(args.results_dir.resolve(), profile)
            if not predictions_path.is_file():
                continue
            run_id = f"swe-bench-lite-{profile}"
            report_dir = args.harness_report_dir.resolve() / run_id
            code, summary_report = run_harness(
                predictions_path=predictions_path,
                run_id=run_id,
                dataset=args.harness_dataset,
                split=args.harness_split,
                report_dir=report_dir,
                max_workers=args.harness_max_workers,
            )
            if code != 0:
                print(
                    f"harness evaluation failed for {profile}; leaving resolved fields unchanged",
                    file=sys.stderr,
                )
                continue
            if summary_report is None:
                print(
                    f"harness evaluation for {profile} produced no summary report",
                    file=sys.stderr,
                )
                continue
            merge_resolved_into_jsonl(
                predictions_path=predictions_path,
                resolved_ids=load_resolved_ids(summary_report),
                summary_report=summary_report,
                run_id=run_id,
            )

    report = compare_profile_outputs(args.results_dir.resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
