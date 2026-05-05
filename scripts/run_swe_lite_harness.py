#!/usr/bin/env python3
"""Run official SWE-bench harness on a predictions JSONL file (Docker required).

Thin wrapper around ``python -m swebench.harness.run_evaluation``.

Usage:
    uv sync --group swe-eval
    uv run python scripts/run_swe_lite_harness.py \\
        --predictions artifacts/lite.predictions.jsonl \\
        --run-id cursor-lite-001

Requires Docker and sufficient disk for harness images.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from scripts.swebench_env import resolve_eval_python


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", "-p", required=True, help="predictions JSONL path")
    parser.add_argument(
        "--dataset",
        "-d",
        default="princeton-nlp/SWE-bench_Lite",
        help="Dataset name or path (default: Lite)",
    )
    parser.add_argument("--split", "-s", default="test", help="Dataset split")
    parser.add_argument("--run-id", "-id", required=True, help="Run identifier for reports")
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel workers")
    parser.add_argument(
        "--report-dir",
        default=".",
        help="Directory where the harness should write its final summary report",
    )
    parser.add_argument(
        "--instance-ids",
        nargs="*",
        help="Optional subset of instance_id values",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Image namespace passed to the harness ('none' for locally-built images, 'swebench' for Docker Hub). Default: harness default.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Pass --clean True to the harness so it removes images above --cache-level after the run.",
    )
    parser.add_argument(
        "--cache-level",
        choices=("none", "base", "env", "instance"),
        default=None,
        help="Pass --cache_level to the harness. Use 'base' with --clean to drop instance and env images.",
    )
    args = parser.parse_args()

    try:
        import swebench  # noqa: F401
    except ImportError as exc:
        eval_python = resolve_eval_python()
        if eval_python != sys.executable:
            return subprocess.call([eval_python, __file__, *sys.argv[1:]])
        raise SystemExit("swebench not installed. Run:  uv sync --group swe-eval") from exc

    if shutil.which("docker") is None:
        print("error: docker not found on PATH", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        args.dataset,
        "--split",
        args.split,
        "--predictions_path",
        args.predictions,
        "--run_id",
        args.run_id,
        "--max_workers",
        str(args.max_workers),
        "--report_dir",
        args.report_dir,
    ]
    if args.instance_ids:
        cmd.extend(["--instance_ids", *args.instance_ids])
    if args.namespace:
        cmd.extend(["--namespace", args.namespace])
    if args.clean:
        cmd.extend(["--clean", "True"])
    if args.cache_level:
        cmd.extend(["--cache_level", args.cache_level])

    print("Running:", " ".join(cmd), file=sys.stderr)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
