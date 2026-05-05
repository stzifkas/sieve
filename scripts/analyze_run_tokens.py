#!/usr/bin/env python3
"""Compare saved Sieve run artifacts by chars and optional exact token counts.

Usage:
    python3 scripts/analyze_run_tokens.py \
      --baseline-meta path/to/baseline.meta.json \
      --sieve-meta path/to/sieve.meta.json

If ``tiktoken`` is installed, pass ``--encoding cl100k_base`` (or another
supported encoding) to compute exact token counts for the raw combined output
and the agent-facing output.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunBundle:
    meta_path: Path
    mode: str
    raw_chars: int
    agent_chars: int
    saved_chars: int
    raw_text: str
    agent_text: str


def _artifact_path(meta_path: Path, suffix: str) -> Path:
    name = meta_path.name
    if not name.endswith(".meta.json"):
        raise ValueError(f"expected .meta.json file, got {meta_path}")
    stem = name[: -len(".meta.json")]
    return meta_path.with_name(f"{stem}.{suffix}")


def load_bundle(meta_path: Path) -> RunBundle:
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    stdout_path = _artifact_path(meta_path, "stdout.txt")
    stderr_path = _artifact_path(meta_path, "stderr.txt")
    agent_path = _artifact_path(meta_path, "agent.txt")
    stdout = stdout_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    agent = agent_path.read_text(encoding="utf-8")
    raw = stdout.rstrip() + ("\n" if stdout and stderr else "") + stderr.lstrip()
    return RunBundle(
        meta_path=meta_path,
        mode=str(data.get("mode", "?")),
        raw_chars=int(data.get("raw_chars", len(raw))),
        agent_chars=int(data.get("agent_chars", len(agent))),
        saved_chars=int(data.get("saved_chars", max(len(raw) - len(agent), 0))),
        raw_text=raw,
        agent_text=agent,
    )


def count_tokens_tiktoken(text: str, encoding_name: str) -> int:
    import tiktoken

    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def render_report(
    *,
    baseline: RunBundle,
    sieve: RunBundle,
    encoding_name: str | None,
) -> str:
    lines: list[str] = []
    lines.append("Saved run comparison")
    lines.append("=" * 60)
    lines.append(f"baseline meta: {baseline.meta_path}")
    lines.append(f"sieve meta:    {sieve.meta_path}")
    lines.append("")
    lines.append(f"{'metric':<22} {'baseline':>14} {'sieve':>14}")
    lines.append("-" * 60)
    lines.append(f"{'raw chars':<22} {baseline.raw_chars:>14} {sieve.raw_chars:>14}")
    lines.append(f"{'agent chars':<22} {baseline.agent_chars:>14} {sieve.agent_chars:>14}")
    lines.append(f"{'saved chars':<22} {baseline.saved_chars:>14} {sieve.saved_chars:>14}")
    lines.append(
        f"{'agent char delta':<22} {'':>14} {baseline.agent_chars - sieve.agent_chars:>14}"
    )

    if encoding_name:
        baseline_raw_tokens = count_tokens_tiktoken(baseline.raw_text, encoding_name)
        baseline_agent_tokens = count_tokens_tiktoken(baseline.agent_text, encoding_name)
        sieve_raw_tokens = count_tokens_tiktoken(sieve.raw_text, encoding_name)
        sieve_agent_tokens = count_tokens_tiktoken(sieve.agent_text, encoding_name)
        lines.append("-" * 60)
        lines.append(f"token encoding: {encoding_name}")
        lines.append(f"{'raw tokens':<22} {baseline_raw_tokens:>14} {sieve_raw_tokens:>14}")
        lines.append(f"{'agent tokens':<22} {baseline_agent_tokens:>14} {sieve_agent_tokens:>14}")
        lines.append(
            f"{'saved tokens':<22} "
            f"{baseline_raw_tokens - baseline_agent_tokens:>14} "
            f"{sieve_raw_tokens - sieve_agent_tokens:>14}"
        )
        lines.append(
            f"{'agent token delta':<22} {'':>14} "
            f"{baseline_agent_tokens - sieve_agent_tokens:>14}"
        )
    else:
        lines.append("-" * 60)
        lines.append("Exact token counts unavailable: install tiktoken and pass --encoding.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-meta", type=Path, required=True)
    parser.add_argument("--sieve-meta", type=Path, required=True)
    parser.add_argument(
        "--encoding",
        help="tiktoken encoding name, e.g. cl100k_base or o200k_base",
    )
    args = parser.parse_args(argv)

    baseline = load_bundle(args.baseline_meta)
    sieve = load_bundle(args.sieve_meta)
    print(render_report(baseline=baseline, sieve=sieve, encoding_name=args.encoding))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
