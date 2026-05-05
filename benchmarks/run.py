"""Compression benchmark.

Runs every fixture in tests/fixtures through CompressSession and prints a
per-sample table plus aggregate ratios. Also runs a multi-turn delta scenario
to show cross-turn savings.

Usage:
    uv run python -m benchmarks.run
    uv run python -m benchmarks.run --json   # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from sieve import CompressSession

from benchmarks.corpus import Sample, load_samples


CHARS_PER_TOKEN = 4  # rough heuristic; matches stats.py


@dataclass
class SampleResult:
    name: str
    category: str
    raw_chars: int
    compressed_chars: int

    @property
    def ratio(self) -> float:
        if self.raw_chars == 0:
            return 0.0
        return 1 - self.compressed_chars / self.raw_chars

    @property
    def raw_tokens(self) -> int:
        return self.raw_chars // CHARS_PER_TOKEN

    @property
    def compressed_tokens(self) -> int:
        return self.compressed_chars // CHARS_PER_TOKEN


def run_single(sample: Sample) -> SampleResult:
    session = CompressSession()
    result = session.compress(
        command=sample.command,
        stdout=sample.stdout,
        stderr=sample.stderr,
        exit_code=sample.exit_code,
    )
    return SampleResult(
        name=sample.name,
        category=sample.category,
        raw_chars=sample.raw_chars,
        compressed_chars=len(result.text),
    )


def run_delta_scenario(turns: int = 5) -> dict:
    """Same pytest output served `turns` times — measures cumulative savings
    when an agent re-encounters identical feedback across iterations."""
    from benchmarks.corpus import FIXTURES

    raw = (FIXTURES / "pytest" / "two_failures.txt").read_text()
    session = CompressSession()
    raw_total = 0
    compressed_total = 0
    per_turn = []
    for turn in range(1, turns + 1):
        result = session.compress(command="pytest tests/", stdout=raw, exit_code=1)
        raw_total += len(raw)
        compressed_total += len(result.text)
        per_turn.append({
            "turn": turn,
            "compressed_chars": len(result.text),
        })
    return {
        "turns": turns,
        "raw_chars_total": raw_total,
        "compressed_chars_total": compressed_total,
        "ratio": 1 - compressed_total / raw_total if raw_total else 0.0,
        "per_turn": per_turn,
    }


def render_text(results: list[SampleResult], delta: dict) -> str:
    lines: list[str] = []
    lines.append("Sieve compression benchmark")
    lines.append("=" * 78)
    lines.append(f"{'sample':<32} {'cat':<8} {'raw':>8} {'cmp':>8} {'ratio':>8}")
    lines.append("-" * 78)
    for r in results:
        lines.append(
            f"{r.name:<32} {r.category:<8} "
            f"{r.raw_chars:>8} {r.compressed_chars:>8} {r.ratio:>7.1%}"
        )

    lines.append("-" * 78)
    by_cat: dict[str, list[SampleResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    for cat, items in sorted(by_cat.items()):
        raw = sum(i.raw_chars for i in items)
        cmp_ = sum(i.compressed_chars for i in items)
        ratio = 1 - cmp_ / raw if raw else 0.0
        lines.append(f"{'  ' + cat:<32} {'agg':<8} {raw:>8} {cmp_:>8} {ratio:>7.1%}")

    raw = sum(r.raw_chars for r in results)
    cmp_ = sum(r.compressed_chars for r in results)
    overall = 1 - cmp_ / raw if raw else 0.0
    lines.append("=" * 78)
    lines.append(
        f"  total ({len(results)} samples): "
        f"raw={raw} cmp={cmp_} ratio={overall:.1%} "
        f"(~{(raw - cmp_) // CHARS_PER_TOKEN} tokens saved)"
    )

    lines.append("")
    lines.append(f"Delta scenario ({delta['turns']} turns of identical pytest output):")
    lines.append(
        f"  raw={delta['raw_chars_total']} cmp={delta['compressed_chars_total']} "
        f"ratio={delta['ratio']:.1%}"
    )
    for entry in delta["per_turn"]:
        lines.append(f"    turn {entry['turn']}: {entry['compressed_chars']} chars")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)

    samples = load_samples()
    results = [run_single(s) for s in samples]
    delta = run_delta_scenario()

    if args.json:
        payload = {
            "samples": [
                {
                    "name": r.name,
                    "category": r.category,
                    "raw_chars": r.raw_chars,
                    "compressed_chars": r.compressed_chars,
                    "ratio": r.ratio,
                }
                for r in results
            ],
            "delta_scenario": delta,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_text(results, delta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
