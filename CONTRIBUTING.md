# Contributing to Sieve

Thanks for contributing. This project is focused on reliable, parser-aware tool-output compression for coding agents, so correctness and reproducibility matter more than flashy changes.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Repository Layout](#repository-layout)
- [Development Workflow](#development-workflow)
- [Testing and Verification](#testing-and-verification)
- [Benchmarks and Evaluation](#benchmarks-and-evaluation)
- [Coding Guidelines](#coding-guidelines)
- [Adding or Updating Parsers](#adding-or-updating-parsers)
- [Pull Request Checklist](#pull-request-checklist)
- [Commit Messages](#commit-messages)
- [Release and Versioning Notes](#release-and-versioning-notes)
- [Security Reporting](#security-reporting)
- [Getting Help](#getting-help)

## Code of Conduct

Be respectful, assume good intent, and keep discussions technical and constructive.

## Ways to Contribute

You can help by:

- Fixing bugs in parsing, delta mode, or output formatting.
- Improving test coverage, fixtures, and benchmark quality.
- Improving integrations (for example MCP proxy behavior).
- Tightening docs, examples, and reproducibility instructions.
- Reporting bugs with minimal reproducible input/output samples.

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- Git
- Optional: Docker (needed for SWE-bench harness runs)

### Clone and install

```bash
git clone <your-fork-or-repo-url>
cd agent_compress
uv sync
```

If you need optional benchmark/eval dependencies:

```bash
uv sync --group swe-eval
```

## Repository Layout

High-level map (actual internals may evolve):

- `src/` - core library and integrations
- `tests/` - unit/integration tests and fixtures
- `benchmarks/` - benchmark runners and comparisons
- `scripts/` - helper scripts, including Sieve-wrapped runners
- `docs/` - design and architecture docs

## Development Workflow

1. Create a branch from `main`.
2. Make focused changes (prefer small, reviewable PRs).
3. Run tests and any relevant benchmark checks.
4. Update docs when behavior or interfaces change.
5. Open a PR with context, rationale, and verification output.

## Testing and Verification

This repo requires verification commands to be run through Sieve so agent-facing output is compressed and consistent with project conventions.

Use:

```bash
PYTHONPATH=src python3 scripts/sieved_run.py -- <command>
```

Examples:

```bash
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m benchmarks.run
```

Do not use baseline mode by default.

If your environment depends on `uv run`, this is also acceptable:

```bash
uv run python scripts/sieved_run.py -- python -m unittest discover -s tests -v
```

### Minimum pre-PR verification

Run these before opening a PR:

```bash
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m benchmarks.run
```

If your change touches MCP integration, parser routing, or benchmark logic, run the most relevant additional checks and include them in your PR notes.

## Benchmarks and Evaluation

For fixture-corpus compression stats:

```bash
uv run python -m benchmarks.run
```

For SWE-bench paired profiles and compare:

```bash
uv sync --group swe-eval
bash scripts/run_cursor_swe_bench_profiles.sh --resume --eval-with-harness --harness-namespace none
PYTHONPATH=src python3 -m benchmarks.swe_bench_compare \
  --baseline artifacts/cursor-swe-bench-lite.baseline.jsonl \
  --sieve    artifacts/cursor-swe-bench-lite.sieve.jsonl
```

For CI-Repair-Bench compression measurement:

```bash
uv sync --group swe-eval
uv run python -m benchmarks.ci_repair_bench --compare --json
```

When sharing benchmark claims in a PR, include:

- Command(s) used
- Dataset/manifest scope
- Baseline vs new values
- Any caveats (for example warm cache, partial subset)

## Coding Guidelines

- Keep changes scoped and obvious.
- Prefer readable, deterministic parsing logic over clever heuristics.
- Preserve "never larger than raw" behavior for compressed output.
- Keep cross-turn delta behavior stable and test-covered.
- Add concise comments only where intent is non-obvious.
- Avoid introducing unrelated refactors in the same PR.

## Adding or Updating Parsers

If you add/modify a parser:

1. Add representative fixtures (including noisy/edge output).
2. Add tests for parsing correctness and formatting output.
3. Add delta-mode expectations if behavior should deduplicate across turns.
4. Verify fallback behavior when parsing fails or signal is weak.
5. Confirm no regression in existing parser routes.

Good parser changes prioritize correctness first, compression ratio second.

## Pull Request Checklist

Before requesting review, confirm:

- [ ] Tests pass locally.
- [ ] Benchmark command(s) relevant to the change were run.
- [ ] New behavior has test coverage.
- [ ] Docs/readme updated if user-facing behavior changed.
- [ ] PR description explains what changed and why.
- [ ] PR includes verification commands and key output summary.
- [ ] No unrelated cleanup bundled into the same PR.

## Commit Messages

Use concise, intent-first messages. A practical format:

```text
<type>: <short summary>

<why this change exists and what it improves>
```

Suggested types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.

## Release and Versioning Notes

If a change affects public API, output format contracts, or integration behavior:

- Call it out explicitly in the PR.
- Update docs and examples.
- Note any migration considerations.

## Security Reporting

If you find a security issue, do not open a public exploit-style issue with sensitive details.
Prefer responsible disclosure through repository maintainers/owners.

## Getting Help

Open an issue or PR discussion with:

- What you expected
- What happened
- Minimal reproducible command/input
- Environment details (OS, Python version, dependency setup)

Clear repros save everyone a lot of time.
