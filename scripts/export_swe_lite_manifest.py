#!/usr/bin/env python3
"""Export SWE-bench Lite instances to JSONL for integrations/swe-bench-lite-cursor.

Each line includes the core repair fields plus the official test metadata needed
to reconstruct the harness instance environment without shipping the oracle fix patch.

Usage:
    uv sync --group swe-eval
    uv run python scripts/export_swe_lite_manifest.py --output benchmarks/manifests/lite_test.jsonl --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", required=True, type=Path, help="JSONL output path")
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench_Lite",
        help="HuggingFace dataset id",
    )
    parser.add_argument("--split", default="test", help="Dataset split")
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0 = all)")
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Missing dependency: install with  uv sync --group swe-eval"
        ) from exc

    ds = load_dataset(args.dataset, split=args.split)
    n = len(ds) if args.limit <= 0 else min(args.limit, len(ds))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as fh:
        for i in range(n):
            row = ds[i]
            record = {
                "instance_id": row["instance_id"],
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "problem_statement": row["problem_statement"],
                "version": row["version"],
                "test_patch": row["test_patch"],
                "FAIL_TO_PASS": row["FAIL_TO_PASS"],
                "PASS_TO_PASS": row["PASS_TO_PASS"],
                "environment_setup_commit": row.get("environment_setup_commit"),
                "hints_text": row.get("hints_text"),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"wrote {n} rows to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
