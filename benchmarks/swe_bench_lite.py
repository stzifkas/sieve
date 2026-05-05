"""Benchmark Sieve against SWE-bench Lite trajectories.

This benchmark operates on agent trajectory files rather than the SWE-bench
task dataset itself. A trajectory directory should contain one `.traj` JSON file
per instance, typically produced by SWE-agent or a similar coding agent.

Usage:
    uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories
    uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories --no-sieve
    uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories --compare
    uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories --json --compare

`--no-sieve` measures baseline trajectory chars (observations unchanged).
`--compare` runs baseline then Sieve and prints both (+ deltas).

Trajectory `.traj` files are produced by SWE-agent (or similar) on SWE-bench Lite runs—not by `swebench.harness.run_evaluation` alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sieve import CompressSession


CHARS_PER_TOKEN = 4
DEFAULT_TRAJ_GLOB = "*.traj"


@dataclass(frozen=True)
class TrajectoryStep:
    instance_id: str
    trajectory_path: Path
    step_index: int
    action: str
    observation: str
    exit_code: int

    @property
    def raw_chars(self) -> int:
        return len(self.observation)


@dataclass(frozen=True)
class StepBenchmarkResult:
    instance_id: str
    trajectory_path: Path
    step_index: int
    parser: str
    raw_chars: int
    compressed_chars: int
    delta_hit: bool
    dedup_hit: bool

    @property
    def ratio(self) -> float:
        if self.raw_chars == 0:
            return 0.0
        return 1 - self.compressed_chars / self.raw_chars


def discover_trajectory_files(root: Path, glob: str = DEFAULT_TRAJ_GLOB) -> list[Path]:
    return sorted(path for path in root.rglob(glob) if path.is_file())


def load_trajectory_steps(root: Path, glob: str = DEFAULT_TRAJ_GLOB) -> list[TrajectoryStep]:
    steps: list[TrajectoryStep] = []
    for path in discover_trajectory_files(root, glob=glob):
        data = json.loads(path.read_text())
        instance_id = _infer_instance_id(path, data)
        trajectory = data.get("trajectory", [])
        if not isinstance(trajectory, list):
            continue

        for step_index, item in enumerate(trajectory):
            if not isinstance(item, dict):
                continue
            observation = item.get("observation")
            if not isinstance(observation, str) or not observation.strip():
                continue
            action = item.get("action")
            action_text = action if isinstance(action, str) and action.strip() else "<unknown>"
            exit_code = _infer_exit_code(item, action_text, observation)
            steps.append(
                TrajectoryStep(
                    instance_id=instance_id,
                    trajectory_path=path,
                    step_index=step_index,
                    action=action_text,
                    observation=observation,
                    exit_code=exit_code,
                )
            )
    return steps


def benchmark_steps(
    steps: list[TrajectoryStep],
    *,
    sieve: bool = True,
) -> list[StepBenchmarkResult]:
    by_instance: dict[str, CompressSession] = {}
    results: list[StepBenchmarkResult] = []
    for step in steps:
        if not sieve:
            results.append(
                StepBenchmarkResult(
                    instance_id=step.instance_id,
                    trajectory_path=step.trajectory_path,
                    step_index=step.step_index,
                    parser="passthrough",
                    raw_chars=step.raw_chars,
                    compressed_chars=step.raw_chars,
                    delta_hit=False,
                    dedup_hit=False,
                )
            )
            continue

        session = by_instance.setdefault(step.instance_id, CompressSession())
        outcome = session.compress(
            command=step.action,
            stdout=step.observation,
            exit_code=step.exit_code,
        )
        results.append(
            StepBenchmarkResult(
                instance_id=step.instance_id,
                trajectory_path=step.trajectory_path,
                step_index=step.step_index,
                parser=outcome.parsed.tool_type,
                raw_chars=step.raw_chars,
                compressed_chars=len(outcome.text),
                delta_hit=bool(outcome.compressed.metadata.get("delta_hit")),
                dedup_hit=bool(outcome.compressed.metadata.get("dedup_hit")),
            )
        )
    return results


def summarize(results: list[StepBenchmarkResult]) -> dict[str, Any]:
    raw_total = sum(item.raw_chars for item in results)
    compressed_total = sum(item.compressed_chars for item in results)
    parser_hits = sum(
        1 for item in results if item.parser not in ("generic", "passthrough")
    )
    delta_hits = sum(1 for item in results if item.delta_hit)
    dedup_hits = sum(1 for item in results if item.dedup_hit)
    unique_instances = len({item.instance_id for item in results})

    by_parser: dict[str, dict[str, int]] = {}
    by_instance: dict[str, dict[str, int]] = {}
    for item in results:
        parser_bucket = by_parser.setdefault(
            item.parser,
            {"steps": 0, "raw_chars": 0, "compressed_chars": 0},
        )
        parser_bucket["steps"] += 1
        parser_bucket["raw_chars"] += item.raw_chars
        parser_bucket["compressed_chars"] += item.compressed_chars

        instance_bucket = by_instance.setdefault(
            item.instance_id,
            {"steps": 0, "raw_chars": 0, "compressed_chars": 0},
        )
        instance_bucket["steps"] += 1
        instance_bucket["raw_chars"] += item.raw_chars
        instance_bucket["compressed_chars"] += item.compressed_chars

    return {
        "instances": unique_instances,
        "steps": len(results),
        "raw_chars": raw_total,
        "compressed_chars": compressed_total,
        "ratio": 1 - compressed_total / raw_total if raw_total else 0.0,
        "estimated_tokens_saved": (raw_total - compressed_total) // CHARS_PER_TOKEN,
        "parser_coverage": parser_hits / len(results) if results else 0.0,
        "delta_hit_rate": delta_hits / len(results) if results else 0.0,
        "dedup_hit_rate": dedup_hits / len(results) if results else 0.0,
        "parsers": {
            parser: {
                **stats,
                "ratio": 1 - stats["compressed_chars"] / stats["raw_chars"]
                if stats["raw_chars"]
                else 0.0,
            }
            for parser, stats in sorted(by_parser.items())
        },
        "instances_detail": {
            instance_id: {
                **stats,
                "ratio": 1 - stats["compressed_chars"] / stats["raw_chars"]
                if stats["raw_chars"]
                else 0.0,
            }
            for instance_id, stats in sorted(by_instance.items())
        },
    }


def render_text(summary: dict[str, Any], results: list[StepBenchmarkResult]) -> str:
    lines: list[str] = []
    lines.append("SWE-bench Lite trajectory benchmark")
    lines.append("=" * 78)
    lines.append(
        f"instances={summary['instances']} steps={summary['steps']} "
        f"raw={summary['raw_chars']} cmp={summary['compressed_chars']} "
        f"ratio={summary['ratio']:.1%}"
    )
    lines.append(
        f"parser coverage={summary['parser_coverage']:.1%} "
        f"(~{summary['estimated_tokens_saved']} tokens saved)"
    )
    lines.append(
        f"delta hit rate={summary['delta_hit_rate']:.1%} "
        f"dedup hit rate={summary['dedup_hit_rate']:.1%}"
    )
    lines.append("")
    lines.append(f"{'parser':<20} {'steps':>8} {'raw':>10} {'cmp':>10} {'ratio':>8}")
    lines.append("-" * 78)
    for parser, stats in summary["parsers"].items():
        lines.append(
            f"{parser:<20} {stats['steps']:>8} {stats['raw_chars']:>10} "
            f"{stats['compressed_chars']:>10} {stats['ratio']:>7.1%}"
        )

    worst = sorted(results, key=lambda item: item.ratio)[:10]
    if worst:
        lines.append("")
        lines.append("Lowest-compression steps")
        lines.append("-" * 78)
        for item in worst:
            lines.append(
                f"{item.instance_id} step={item.step_index} parser={item.parser} "
                f"raw={item.raw_chars} cmp={item.compressed_chars} ratio={item.ratio:.1%}"
            )
    return "\n".join(lines)


def render_compare(
    baseline_summary: dict[str, Any],
    sieve_summary: dict[str, Any],
    *,
    label_off: str = "sieve off",
    label_on: str = "sieve on",
) -> str:
    lines: list[str] = []
    lines.append("SWE-bench Lite trajectories — sieve off vs on")
    lines.append("=" * 78)
    w = 26
    lines.append(f"{'metric':<{w}} {label_off:>24} {label_on:>24}")
    lines.append("-" * 78)
    lines.append(
        f"{'instances':<{w}} {baseline_summary['instances']:>24} "
        f"{sieve_summary['instances']:>24}"
    )
    lines.append(
        f"{'steps':<{w}} {baseline_summary['steps']:>24} "
        f"{sieve_summary['steps']:>24}"
    )
    lines.append(
        f"{'observation chars (total)':<{w}} {baseline_summary['raw_chars']:>24} "
        f"{sieve_summary['compressed_chars']:>24}"
    )
    lines.append(
        f"{'compression ratio':<{w}} {baseline_summary['ratio']:>23.1%} "
        f"{sieve_summary['ratio']:>23.1%}"
    )
    est_off = baseline_summary["estimated_tokens_saved"]
    est_on = sieve_summary["estimated_tokens_saved"]
    lines.append(
        f"{'~tokens saved (chars/4)':<{w}} {est_off:>24} {est_on:>24}"
    )
    char_delta = baseline_summary["raw_chars"] - sieve_summary["compressed_chars"]
    tok_delta = char_delta // CHARS_PER_TOKEN if char_delta > 0 else 0
    lines.append("-" * 78)
    lines.append(
        f"{'delta (baseline chars − sieve chars)':<{w}} {'':>24} {char_delta:>24}"
    )
    lines.append(f"{'approx token-equivalent of delta':<{w}} {'':>24} {tok_delta:>24}")
    return "\n".join(lines)


def _infer_instance_id(path: Path, data: dict[str, Any]) -> str:
    for key in ("instance_id", "problem_statement_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return path.stem


def _infer_exit_code(step: dict[str, Any], action: str, observation: str) -> int:
    for key in ("exit_code", "returncode", "return_code"):
        value = step.get(key)
        if isinstance(value, int):
            return value

    lower_obs = observation.lower()
    lower_action = action.lower()
    if "traceback (most recent call last):" in observation:
        return 1
    if re.search(r"^[a-z_][\w.]+(?:error|exception|interrupt|exit|group):", observation, re.MULTILINE | re.IGNORECASE):
        return 1
    if "pytest" in lower_action:
        if any(token in lower_obs for token in (" failed", " error", "failures", "short test summary info")):
            return 1
        return 0
    if any(token in lower_action for token in ("mypy", "eslint", "tsc", "gcc", "clang", "pip install")) and "error" in lower_obs:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traj-dir", required=True, help="directory containing .traj files")
    parser.add_argument("--glob", default=DEFAULT_TRAJ_GLOB, help="trajectory filename glob")
    parser.add_argument("--limit", type=int, default=0, help="max number of trajectory steps to benchmark")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--compare",
        action="store_true",
        help="run sieve off then sieve on and print comparison",
    )
    mode.add_argument(
        "--no-sieve",
        action="store_true",
        help="baseline only: observations unchanged (no compression)",
    )
    args = parser.parse_args(argv)

    root = Path(args.traj_dir)
    steps = load_trajectory_steps(root, glob=args.glob)
    if args.limit > 0:
        steps = steps[: args.limit]
    if not steps:
        print("No trajectory steps found (check --traj-dir and .traj format).", file=sys.stderr)
        return 1

    if args.compare:
        base_results = benchmark_steps(steps, sieve=False)
        base_summary = summarize(base_results)
        sieve_results = benchmark_steps(steps, sieve=True)
        sieve_summary = summarize(sieve_results)
        if args.json:
            payload = {
                "baseline": {
                    "summary": base_summary,
                    "steps": _steps_to_jsonable(base_results),
                },
                "sieve": {
                    "summary": sieve_summary,
                    "steps": _steps_to_jsonable(sieve_results),
                },
                "delta_chars": base_summary["raw_chars"] - sieve_summary["compressed_chars"],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(render_compare(base_summary, sieve_summary))
            print()
            print(render_text(base_summary, base_results))
            print()
            print(render_text(sieve_summary, sieve_results))
        return 0

    sieve_enabled = not args.no_sieve
    results = benchmark_steps(steps, sieve=sieve_enabled)
    summary = summarize(results)

    if args.json:
        payload = {
            "mode": "sieve" if sieve_enabled else "baseline",
            "summary": summary,
            "steps": _steps_to_jsonable(results),
        }
        print(json.dumps(payload, indent=2))
    else:
        tag = " (sieve on)" if sieve_enabled else " (sieve off / baseline)"
        lines = render_text(summary, results).splitlines()
        if lines:
            lines[0] = lines[0] + tag
        print("\n".join(lines))
    return 0


def _steps_to_jsonable(results: list[StepBenchmarkResult]) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": item.instance_id,
            "trajectory_path": str(item.trajectory_path),
            "step_index": item.step_index,
            "parser": item.parser,
            "raw_chars": item.raw_chars,
            "compressed_chars": item.compressed_chars,
            "delta_hit": item.delta_hit,
            "dedup_hit": item.dedup_hit,
            "ratio": item.ratio,
        }
        for item in results
    ]


if __name__ == "__main__":
    sys.exit(main())
