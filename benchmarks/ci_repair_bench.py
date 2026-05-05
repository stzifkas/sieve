"""Benchmark Sieve on CI-Repair-Bench-style observations (GitHub Actions logs).

Loads `ci-benchmark-user/ci-repair-bench` (567 instances). Each synthetic observation
concatenates **workflow YAML** + **flattened CI logs** — the high-noise signal agents
actually stare at. We intentionally **omit** the gold ``diff`` so this measures
compression of diagnostic context, not leakage of the fix.

Paper: CI-Repair-Bench (arXiv:2604.27148). Dataset: Hugging Face ``ci-benchmark-user/ci-repair-bench``.

Usage:
    uv sync --group swe-eval
    uv run python -m benchmarks.ci_repair_bench
    uv run python -m benchmarks.ci_repair_bench --limit 50 --json
    uv run python -m benchmarks.ci_repair_bench --compare
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

from sieve import CompressSession

CHARS_PER_TOKEN = 4
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TIMESTAMP_RE = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")
GHA_MARKER_RE = re.compile(r"^##\[(?:group|endgroup|error|warning|notice|debug)\]")
RUN_LINE_RE = re.compile(r"^Run\s+(?P<command>.+?)\s*$")
STREAM_PREFIX_RE = re.compile(r"^(stdout|stderr):\s*")
NOISE_PREFIXES = (
    "Current runner version:",
    "Prepare workflow directory",
    "Prepare all required actions",
    "Getting action download info",
    "Download action repository ",
    "Post job cleanup.",
    "Cleaning up orphan processes",
    "Secret source:",
    "Complete job name:",
    "Temporarily overriding HOME=",
    "Adding repository directory to the temporary git global config as a safe directory",
)
NOISE_LINES = {
    "Runner Image Provisioner",
    "Operating System",
    "Runner Image",
    "GITHUB_TOKEN Permissions",
}


@dataclass(frozen=True)
class CIRepairStep:
    name: str
    command: str
    raw_log: str
    normalized_log: str

    @property
    def raw_chars(self) -> int:
        return len(self.raw_log)

    @property
    def normalized_chars(self) -> int:
        return len(self.normalized_log)


@dataclass(frozen=True)
class CIRepairRow:
    instance_id: str
    repo_label: str
    workflow_name: str
    error_types: tuple[str, ...]
    workflow: str
    steps: tuple[CIRepairStep, ...]
    exit_code: int = 1

    @property
    def observation(self) -> str:
        return render_observation(self.workflow, self.steps)


@dataclass(frozen=True)
class CIRepairStepBenchmarkResult:
    parser: str
    command: str
    step_name: str
    raw_chars: int
    compressed_chars: int
    delta_hit: bool
    dedup_hit: bool

    @property
    def ratio(self) -> float:
        if self.raw_chars == 0:
            return 0.0
        return 1 - self.compressed_chars / self.raw_chars


@dataclass(frozen=True)
class CIRepairBenchmarkResult:
    instance_id: str
    workflow_chars: int
    step_results: tuple[CIRepairStepBenchmarkResult, ...]
    raw_chars: int
    compressed_chars: int
    error_types: tuple[str, ...]

    @property
    def ratio(self) -> float:
        if self.raw_chars == 0:
            return 0.0
        return 1 - self.compressed_chars / self.raw_chars


def flatten_logs(logs: Any) -> str:
    """Turn HF ``logs`` list into one markdown-ish blob."""
    if not isinstance(logs, list):
        return ""
    parts: list[str] = []
    for i, item in enumerate(logs):
        if not isinstance(item, dict):
            continue
        log_text = item.get("log") or ""
        if not isinstance(log_text, str):
            log_text = str(log_text)
        step = item.get("step_name") or item.get("setp_name") or item.get("name") or ""
        if isinstance(step, str) and step.strip():
            header = f"## Step: {step.strip()}\n"
        else:
            header = f"## Log chunk {i}\n"
        parts.append(header + log_text)
    return "\n\n".join(parts)


def _normalize_gha_line(line: str) -> str | None:
    line = line.lstrip("\ufeff")
    line = ANSI_RE.sub("", line)
    line = TIMESTAMP_RE.sub("", line)
    line = GHA_MARKER_RE.sub("", line).strip()
    if line.startswith("[command]/"):
        line = line[len("[command]/") :].strip()
    line = STREAM_PREFIX_RE.sub("", line).strip()
    if not line:
        return None
    if line in NOISE_LINES:
        return None
    if line.startswith(NOISE_PREFIXES):
        return None
    if line.startswith(("shell:", "env:")):
        return None
    return line


def _split_log_into_steps(
    log_text: str,
    *,
    fallback_name: str,
    fallback_command: str,
) -> list[CIRepairStep]:
    raw_lines = log_text.splitlines()
    steps: list[CIRepairStep] = []
    current_name = fallback_name
    current_command = fallback_command
    current_raw: list[str] = []
    current_norm: list[str] = []
    saw_run_marker = False

    def flush() -> None:
        nonlocal current_raw, current_norm, current_name, current_command
        if not current_raw and not current_norm:
            return
        normalized_log = "\n".join(line for line in current_norm if line).strip()
        raw_log = "\n".join(current_raw).strip()
        if not raw_log and not normalized_log:
            return
        steps.append(
            CIRepairStep(
                name=current_name,
                command=current_command,
                raw_log=raw_log,
                normalized_log=normalized_log,
            )
        )
        current_raw = []
        current_norm = []

    for raw_line in raw_lines:
        normalized = _normalize_gha_line(raw_line)
        run_match = RUN_LINE_RE.match(normalized or "")
        if run_match:
            saw_run_marker = True
            flush()
            current_command = run_match.group("command").strip()
            current_name = current_command
            continue
        if normalized is None:
            continue
        current_raw.append(raw_line.rstrip())
        current_norm.append(normalized)

    flush()
    if steps or saw_run_marker:
        return steps

    normalized_lines = [
        line for line in (_normalize_gha_line(raw_line) for raw_line in raw_lines) if line
    ]
    return [
        CIRepairStep(
            name=fallback_name,
            command=fallback_command,
            raw_log=log_text.strip(),
            normalized_log="\n".join(normalized_lines).strip(),
        )
    ]


def extract_steps(logs: Any, *, workflow_name: str = "github actions") -> tuple[CIRepairStep, ...]:
    if not isinstance(logs, list):
        return ()
    steps: list[CIRepairStep] = []
    for i, item in enumerate(logs):
        if not isinstance(item, dict):
            continue
        raw_log = item.get("log") or ""
        if not isinstance(raw_log, str):
            raw_log = str(raw_log)
        step_name = item.get("step_name") or item.get("setp_name") or item.get("name") or ""
        if not isinstance(step_name, str) or not step_name.strip():
            step_name = f"log chunk {i}"
        fallback_command = step_name
        steps.extend(
            _split_log_into_steps(
                raw_log,
                fallback_name=step_name.strip(),
                fallback_command=fallback_command.strip(),
            )
        )
    return tuple(step for step in steps if step.raw_log or step.normalized_log)


def render_observation(workflow: str, steps: tuple[CIRepairStep, ...]) -> str:
    parts: list[str] = []
    if workflow.strip():
        parts.append(f"# Workflow (YAML)\n{workflow.strip()}")
    if steps:
        rendered_steps = []
        for step in steps:
            body = step.normalized_log or step.raw_log
            rendered_steps.append(
                f"## Step: {step.name}\n$ {step.command}\n{body}".rstrip()
            )
        parts.append("# CI execution logs\n" + "\n\n".join(rendered_steps))
    return "\n\n".join(parts).strip()


def build_observation(row: dict[str, Any]) -> str:
    """Workflow file contents + normalized CI step logs (no oracle patch)."""
    wf = row.get("workflow") or ""
    if not isinstance(wf, str):
        wf = str(wf)
    steps = extract_steps(row.get("logs"), workflow_name=str(row.get("workflow_name") or ""))
    return render_observation(wf, steps)


def _error_types_tuple(row: dict[str, Any]) -> tuple[str, ...]:
    raw = row.get("error_type")
    if isinstance(raw, list):
        return tuple(str(x) for x in raw if x is not None)
    if raw is None:
        return ()
    return (str(raw),)


def load_hf_rows(*, limit: int = 0) -> list[CIRepairRow]:
    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Missing dependency: install with  uv sync --group swe-eval"
        ) from exc

    ds = load_dataset("ci-benchmark-user/ci-repair-bench", split="train")
    n = len(ds) if limit <= 0 else min(limit, len(ds))
    out: list[CIRepairRow] = []
    for i in range(n):
        row = ds[i]
        oid = str(row["id"])
        owner = row.get("repo_owner") or ""
        name = row.get("repo_name") or ""
        repo_label = f"{owner}/{name}".strip("/")
        workflow = row.get("workflow") or ""
        if not isinstance(workflow, str):
            workflow = str(workflow)
        out.append(
            CIRepairRow(
                instance_id=oid,
                repo_label=repo_label,
                workflow_name=str(row.get("workflow_name") or ""),
                error_types=_error_types_tuple(row),
                workflow=workflow,
                steps=extract_steps(row.get("logs"), workflow_name=str(row.get("workflow_name") or "")),
                exit_code=1,
            )
        )
    return out


def _derive_command(row: CIRepairRow) -> str:
    if row.error_types:
        return "CI failure / " + ", ".join(row.error_types)
    return row.workflow_name or "github actions"


def benchmark_rows(
    rows: list[CIRepairRow],
    *,
    sieve: bool = True,
) -> list[CIRepairBenchmarkResult]:
    sessions: dict[str, CompressSession] = {}
    results: list[CIRepairBenchmarkResult] = []
    for row in rows:
        workflow_chars = len(row.workflow)
        raw_chars = workflow_chars + sum(step.raw_chars for step in row.steps)
        if not sieve:
            step_results = tuple(
                CIRepairStepBenchmarkResult(
                    parser="passthrough",
                    command=step.command,
                    step_name=step.name,
                    raw_chars=step.raw_chars,
                    compressed_chars=step.raw_chars,
                    delta_hit=False,
                    dedup_hit=False,
                )
                for step in row.steps
            )
            results.append(
                CIRepairBenchmarkResult(
                    instance_id=row.instance_id,
                    workflow_chars=workflow_chars,
                    step_results=step_results,
                    raw_chars=raw_chars,
                    compressed_chars=workflow_chars + sum(s.compressed_chars for s in step_results),
                    error_types=row.error_types,
                )
            )
            continue

        session = sessions.setdefault(row.instance_id, CompressSession())
        step_results_list: list[CIRepairStepBenchmarkResult] = []
        for step in row.steps:
            cmd = step.command or _derive_command(row)
            stdout = step.normalized_log or step.raw_log
            outcome = session.compress(
                command=cmd,
                stdout=stdout,
                exit_code=row.exit_code,
            )
            step_results_list.append(
                CIRepairStepBenchmarkResult(
                    parser=outcome.parsed.tool_type,
                    command=cmd,
                    step_name=step.name,
                    raw_chars=step.raw_chars,
                    compressed_chars=len(outcome.text),
                    delta_hit=bool(outcome.compressed.metadata.get("delta_hit")),
                    dedup_hit=bool(outcome.compressed.metadata.get("dedup_hit")),
                )
            )
        step_results = tuple(step_results_list)
        results.append(
            CIRepairBenchmarkResult(
                instance_id=row.instance_id,
                workflow_chars=workflow_chars,
                step_results=step_results,
                raw_chars=raw_chars,
                compressed_chars=workflow_chars + sum(s.compressed_chars for s in step_results),
                error_types=row.error_types,
            )
        )
    return results


def summarize(results: list[CIRepairBenchmarkResult]) -> dict[str, Any]:
    workflow_total = sum(r.workflow_chars for r in results)
    raw_total = sum(r.raw_chars for r in results)
    cmp_total = sum(r.compressed_chars for r in results)
    log_raw_total = raw_total - workflow_total
    total_steps = sum(len(r.step_results) for r in results)
    parser_hits = sum(
        1
        for r in results
        for step in r.step_results
        if step.parser not in ("generic", "passthrough")
    )
    delta_hits = sum(1 for r in results for step in r.step_results if step.delta_hit)
    dedup_hits = sum(1 for r in results for step in r.step_results if step.dedup_hit)

    by_parser: dict[str, dict[str, int]] = {}
    by_error: dict[str, dict[str, int]] = {}
    for r in results:
        for step in r.step_results:
            pk = by_parser.setdefault(
                step.parser,
                {"steps": 0, "raw_chars": 0, "compressed_chars": 0},
            )
            pk["steps"] += 1
            pk["raw_chars"] += step.raw_chars
            pk["compressed_chars"] += step.compressed_chars

        ek = "/".join(sorted(r.error_types)) if r.error_types else "(none)"
        eb = by_error.setdefault(
            ek,
            {"instances": 0, "raw_chars": 0, "compressed_chars": 0},
        )
        eb["instances"] += 1
        eb["raw_chars"] += r.raw_chars
        eb["compressed_chars"] += r.compressed_chars

    return {
        "instances": len(results),
        "steps": total_steps,
        "workflow_chars": workflow_total,
        "log_chars": log_raw_total,
        "raw_chars": raw_total,
        "compressed_chars": cmp_total,
        "ratio": 1 - cmp_total / raw_total if raw_total else 0.0,
        "estimated_tokens_saved": (raw_total - cmp_total) // CHARS_PER_TOKEN,
        "parser_coverage": parser_hits / total_steps if total_steps else 0.0,
        "delta_hit_rate": delta_hits / total_steps if total_steps else 0.0,
        "dedup_hit_rate": dedup_hits / total_steps if total_steps else 0.0,
        "parsers": {
            p: {
                **st,
                "ratio": 1 - st["compressed_chars"] / st["raw_chars"]
                if st["raw_chars"]
                else 0.0,
            }
            for p, st in sorted(by_parser.items())
        },
        "error_types": {
            e: {
                **st,
                "ratio": 1 - st["compressed_chars"] / st["raw_chars"]
                if st["raw_chars"]
                else 0.0,
            }
            for e, st in sorted(by_error.items())
        },
    }


def render_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("CI-Repair-Bench observation compression (workflow + normalized CI steps, no diff)")
    lines.append("=" * 78)
    lines.append(
        f"instances={summary['instances']} steps={summary['steps']} "
        f"raw={summary['raw_chars']} "
        f"cmp={summary['compressed_chars']} ratio={summary['ratio']:.1%}"
    )
    lines.append(
        f"workflow chars={summary['workflow_chars']} "
        f"log chars={summary['log_chars']}"
    )
    lines.append(
        f"parser coverage={summary['parser_coverage']:.1%} "
        f"(~{summary['estimated_tokens_saved']} tokens saved est.)"
    )
    lines.append(
        f"delta hit rate={summary['delta_hit_rate']:.1%} "
        f"dedup hit rate={summary['dedup_hit_rate']:.1%}"
    )
    lines.append("")
    lines.append(f"{'parser':<22} {'steps':>6} {'raw':>12} {'cmp':>12} {'ratio':>8}")
    lines.append("-" * 78)
    for parser, st in summary["parsers"].items():
        lines.append(
            f"{parser:<22} {st['steps']:>6} {st['raw_chars']:>12} "
            f"{st['compressed_chars']:>12} {st['ratio']:>7.1%}"
        )
    lines.append("")
    lines.append("By annotated CI error_type (top 15 by raw chars)")
    lines.append("-" * 78)
    errs = sorted(
        summary["error_types"].items(),
        key=lambda kv: kv[1]["raw_chars"],
        reverse=True,
    )[:15]
    for label, st in errs:
        short = label[:52] + ("…" if len(label) > 53 else "")
        lines.append(
            f"{short:<54} {st['instances']:>4} {st['ratio']:>7.1%}"
        )
    return "\n".join(lines)


def render_compare(base: dict[str, Any], sieve_s: dict[str, Any]) -> str:
    lines = [
        "CI-Repair-Bench — sieve off vs on (observation chars)",
        "=" * 78,
        f"{'metric':<34} {'baseline':>20} {'sieve':>20}",
        "-" * 78,
        f"{'instances':<34} {base['instances']:>20} {sieve_s['instances']:>20}",
        f"{'total raw observation chars':<34} {base['raw_chars']:>20} {sieve_s['compressed_chars']:>20}",
        f"{'compression ratio':<34} {base['ratio']:>19.1%} {sieve_s['ratio']:>19.1%}",
        "-" * 78,
        f"{'delta chars (baseline − sieve)':<34} {'':>20} {base['raw_chars'] - sieve_s['compressed_chars']:>20}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Max instances (0=all 567)")
    parser.add_argument("--json", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--compare", action="store_true")
    mode.add_argument("--no-sieve", action="store_true")
    args = parser.parse_args(argv)

    rows = load_hf_rows(limit=args.limit)
    if not rows:
        print("No rows loaded.", file=sys.stderr)
        return 1

    if args.compare:
        b_results = benchmark_rows(rows, sieve=False)
        b_sum = summarize(b_results)
        s_results = benchmark_rows(rows, sieve=True)
        s_sum = summarize(s_results)
        if args.json:
            print(
                json.dumps(
                    {
                        "baseline": {"summary": b_sum},
                        "sieve": {"summary": s_sum},
                        "delta_chars": b_sum["raw_chars"] - s_sum["compressed_chars"],
                    },
                    indent=2,
                )
            )
        else:
            print(render_compare(b_sum, s_sum))
            print()
            print(render_text(b_sum))
            print()
            print(render_text(s_sum))
        return 0

    sieve_on = not args.no_sieve
    results = benchmark_rows(rows, sieve=sieve_on)
    summary = summarize(results)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "sieve" if sieve_on else "baseline",
                    "summary": summary,
                    "instances": [
                        {
                            "instance_id": r.instance_id,
                            "workflow_chars": r.workflow_chars,
                            "steps": [
                                {
                                    "parser": step.parser,
                                    "command": step.command,
                                    "step_name": step.step_name,
                                    "raw_chars": step.raw_chars,
                                    "compressed_chars": step.compressed_chars,
                                    "ratio": step.ratio,
                                    "delta_hit": step.delta_hit,
                                    "dedup_hit": step.dedup_hit,
                                }
                                for step in r.step_results
                            ],
                            "error_types": list(r.error_types),
                            "raw_chars": r.raw_chars,
                            "compressed_chars": r.compressed_chars,
                            "ratio": r.ratio,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
    else:
        tag = "" if sieve_on else " (baseline / sieve off)"
        header = render_text(summary).splitlines()
        if header:
            header[0] = header[0] + tag
        print("\n".join(header))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
