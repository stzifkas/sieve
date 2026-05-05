"""Compare SWE-bench Lite agent runs with sieve off vs on.

Consumes JSONL result files emitted by the SWE-bench Lite integrations and
compares two profiles on the same set of instances:

- resolved / solved outcomes, when present
- whether the agent produced a non-empty patch
- agent-facing observation chars (`agent_chars`)
- raw observation chars (`raw_chars`)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _resolved_state(row: dict[str, Any]) -> bool | None:
    if "resolved" in row:
        value = row.get("resolved")
        if value is None:
            return None
        return bool(value)
    if "solved" in row:
        value = row.get("solved")
        if value is None:
            return None
        return bool(value)
    return None


def _has_patch(row: dict[str, Any]) -> bool:
    patch = row.get("model_patch")
    if isinstance(patch, str):
        return bool(patch.strip())
    return bool(row.get("has_patch"))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = sum(1 for row in rows if _resolved_state(row) is True)
    resolved_known = sum(1 for row in rows if _resolved_state(row) is not None)
    with_patch = sum(1 for row in rows if _has_patch(row))
    raw_chars = sum(int((row.get("context") or {}).get("raw_chars", 0)) for row in rows)
    agent_chars = sum(int((row.get("context") or {}).get("agent_chars", 0)) for row in rows)
    patch_chars = sum(len(str(row.get("model_patch", ""))) for row in rows)
    return {
        "instances": len(rows),
        "resolved": resolved,
        "resolved_known": resolved_known,
        "resolved_unknown": max(len(rows) - resolved_known, 0),
        "resolve_rate": (resolved / len(rows)) if (rows and resolved_known) else None,
        "scored_rate": (resolved_known / len(rows)) if rows else 0.0,
        "scored_resolve_rate": (resolved / resolved_known) if resolved_known else None,
        "with_patch": with_patch,
        "patch_rate": with_patch / len(rows) if rows else 0.0,
        "patch_chars": patch_chars,
        "raw_chars": raw_chars,
        "agent_chars": agent_chars,
        "ratio": 1 - agent_chars / raw_chars if raw_chars else 0.0,
        "saved_chars": max(raw_chars - agent_chars, 0),
    }


def compare_rows(
    baseline_rows: list[dict[str, Any]],
    sieve_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_map = {str(row["instance_id"]): row for row in baseline_rows if "instance_id" in row}
    sieve_map = {str(row["instance_id"]): row for row in sieve_rows if "instance_id" in row}
    instance_ids = sorted(set(baseline_map) & set(sieve_map))

    paired: list[dict[str, Any]] = []
    for instance_id in instance_ids:
        baseline = baseline_map[instance_id]
        sieve = sieve_map[instance_id]
        baseline_resolved = _resolved_state(baseline)
        sieve_resolved = _resolved_state(sieve)
        paired.append(
            {
                "instance_id": instance_id,
                "baseline_resolved": baseline_resolved,
                "sieve_resolved": sieve_resolved,
                "baseline_has_patch": _has_patch(baseline),
                "sieve_has_patch": _has_patch(sieve),
                "baseline_agent_chars": int((baseline.get("context") or {}).get("agent_chars", 0)),
                "sieve_agent_chars": int((sieve.get("context") or {}).get("agent_chars", 0)),
                "raw_chars": int((baseline.get("context") or {}).get("raw_chars", 0)),
            }
        )

    baseline_summary = summarize([baseline_map[i] for i in instance_ids])
    sieve_summary = summarize([sieve_map[i] for i in instance_ids])
    improved = sum(
        1 for row in paired if row["baseline_resolved"] is False and row["sieve_resolved"] is True
    )
    regressed = sum(
        1 for row in paired if row["baseline_resolved"] is True and row["sieve_resolved"] is False
    )
    unknown = sum(
        1
        for row in paired
        if row["baseline_resolved"] is None or row["sieve_resolved"] is None
    )
    same = len(paired) - improved - regressed - unknown

    return {
        "instances_compared": len(paired),
        "baseline": baseline_summary,
        "sieve": sieve_summary,
        "resolved_delta": sieve_summary["resolved"] - baseline_summary["resolved"],
        "patch_delta": sieve_summary["with_patch"] - baseline_summary["with_patch"],
        "saved_char_delta": baseline_summary["agent_chars"] - sieve_summary["agent_chars"],
        "paired_outcomes": {
            "improved": improved,
            "regressed": regressed,
            "same": same,
            "unknown": unknown,
        },
        "rows": paired,
    }


def render_text(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    sieve = report["sieve"]

    def _fmt_rate(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{value:>19.1%}"

    lines: list[str] = []
    lines.append("SWE-bench Lite comparison — sieve off vs on")
    lines.append("=" * 78)
    lines.append(f"{'metric':<28} {'baseline':>20} {'sieve':>20}")
    lines.append("-" * 78)
    lines.append(f"{'instances':<28} {baseline['instances']:>20} {sieve['instances']:>20}")
    lines.append(f"{'resolved':<28} {baseline['resolved']:>20} {sieve['resolved']:>20}")
    lines.append(f"{'resolved known':<28} {baseline['resolved_known']:>20} {sieve['resolved_known']:>20}")
    lines.append(f"{'resolved unknown':<28} {baseline['resolved_unknown']:>20} {sieve['resolved_unknown']:>20}")
    lines.append(f"{'resolve rate (overall)':<28} {_fmt_rate(baseline['resolve_rate']):>20} {_fmt_rate(sieve['resolve_rate']):>20}")
    lines.append(f"{'resolve rate (of scored)':<28} {_fmt_rate(baseline['scored_resolve_rate']):>20} {_fmt_rate(sieve['scored_resolve_rate']):>20}")
    lines.append(f"{'scored rate':<28} {_fmt_rate(baseline['scored_rate']):>20} {_fmt_rate(sieve['scored_rate']):>20}")
    lines.append(f"{'non-empty patches':<28} {baseline['with_patch']:>20} {sieve['with_patch']:>20}")
    lines.append(f"{'patch chars':<28} {baseline['patch_chars']:>20} {sieve['patch_chars']:>20}")
    lines.append(f"{'agent-facing chars':<28} {baseline['agent_chars']:>20} {sieve['agent_chars']:>20}")
    lines.append(f"{'raw chars':<28} {baseline['raw_chars']:>20} {sieve['raw_chars']:>20}")
    lines.append(f"{'compression ratio':<28} {baseline['ratio']:>19.1%} {sieve['ratio']:>19.1%}")
    lines.append("-" * 78)
    lines.append(f"{'resolved delta':<28} {'':>20} {report['resolved_delta']:>20}")
    lines.append(f"{'patch delta':<28} {'':>20} {report['patch_delta']:>20}")
    lines.append(f"{'saved char delta':<28} {'':>20} {report['saved_char_delta']:>20}")
    lines.append(
        f"{'paired outcomes i/r/s':<28} {'':>20} "
        f"{report['paired_outcomes']['improved']}/"
        f"{report['paired_outcomes']['regressed']}/"
        f"{report['paired_outcomes']['same']:>14}"
    )
    lines.append(
        f"{'paired outcomes unknown':<28} {'':>20} {report['paired_outcomes']['unknown']:>20}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="baseline profile JSONL")
    parser.add_argument("--sieve", type=Path, required=True, help="sieve profile JSONL")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = compare_rows(load_rows(args.baseline), load_rows(args.sieve))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
