from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.swebench_env import resolve_eval_python

ROOT = Path(__file__).resolve().parents[1]


def run_harness(
    *,
    predictions_path: Path,
    run_id: str,
    dataset: str,
    split: str,
    report_dir: Path,
    max_workers: int,
    namespace: str | None = None,
    clean: bool = False,
    cache_level: str | None = None,
) -> tuple[int, Path | None]:
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        resolve_eval_python(),
        str(ROOT / "scripts" / "run_swe_lite_harness.py"),
        "--predictions",
        str(predictions_path),
        "--dataset",
        dataset,
        "--split",
        split,
        "--run-id",
        run_id,
        "--max-workers",
        str(max_workers),
        "--report-dir",
        str(report_dir),
    ]
    if namespace:
        cmd.extend(["--namespace", namespace])
    if clean:
        cmd.append("--clean")
    if cache_level:
        cmd.extend(["--cache-level", cache_level])
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode, find_summary_report(report_dir=report_dir, run_id=run_id)


def find_summary_report(*, report_dir: Path, run_id: str) -> Path | None:
    matches = sorted(report_dir.glob(f"*.{run_id}.json"))
    if matches:
        return matches[-1]
    return None


def load_resolved_ids(summary_report: Path) -> set[str]:
    payload = json.loads(summary_report.read_text(encoding="utf-8"))
    return {str(item) for item in payload.get("resolved_ids", [])}


def merge_resolved_into_jsonl(
    *,
    predictions_path: Path,
    resolved_ids: set[str],
    summary_report: Path,
    run_id: str,
) -> None:
    rows: list[dict] = []
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        row["resolved"] = str(row.get("instance_id")) in resolved_ids
        harness = dict(row.get("harness") or {})
        harness.update({
            "status": "scored",
            "run_id": run_id,
            "summary_report": str(summary_report),
        })
        row["harness"] = harness
        rows.append(row)

    with predictions_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
