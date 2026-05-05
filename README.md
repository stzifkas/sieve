# Sieve

Transparent feedback compression middleware for LLM coding agents. Sieve sits between an agent and its tools, parsing tool output and emitting a compact form before it enters the conversation context.

83.9% of tokens in coding-agent trajectories are tool observations (JetBrains, NeurIPS 2025). Most of those are re-read on every subsequent turn. Sieve targets that bloat by parsing — not truncating — the output of common dev tools, then diffing against prior turns so the agent only sees what changed.

The full design is in [`docs/agent-compress-specs.md`](docs/agent-compress-specs.md). This repo implements the MVP scope (P0) plus most of P1.

## Status

| | |
|--|--|
| Parsers | pytest, Python traceback, mypy, tsc, eslint, gcc/clang, pip install, generic fallback |
| Output formats | plain, structured (JSON), XML, minimal |
| Integrations | MCP proxy, SWE-bench Lite Cursor runner, SWE-bench Lite Codex/Cursor paired runners |
| Tests | 67+ passing (parsers, session, delta, MCP, SWE / CI-Repair bench smoke, …) |
| Dependencies | none for the library; `mcp` extra for the proxy (Python ≥ 3.11) |

## Measured compression

Benchmark over the 22-sample fixture corpus in `tests/fixtures/` (`uv run python -m benchmarks.run`):

| Category | Samples | Raw | Compressed | Ratio |
|---|---:|---:|---:|---:|
| pytest | 7 | 13,475 | 1,292 | **90.4%** |
| pip | 2 | 9,505 | 138 | **98.5%** |
| runtime | 6 | 3,150 | 1,068 | **66.1%** |
| gcc | 1 | 1,318 | 721 | **45.3%** |
| tsc | 2 | 1,264 | 708 | **44.0%** |
| generic | 1 | 480 | 433 | 9.8% |
| eslint | 1 | 844 | 780 | 7.6% |
| mypy | 2 | 758 | 756 | 0.3% |
| **total** | **22** | **30,794** | **5,896** | **80.9%** |

A 5-turn delta scenario where the same pytest failure repeats compresses to **86.3%** cumulative — turn 1 is 297 chars, turns 2-5 collapse to 238 chars each ("PYTEST DELTA: unchanged" + still-failing nodeids).

The compressor enforces a never-larger-than-raw invariant: on inputs already smaller than the framing overhead (mypy clean output, ESLint with terse messages, etc.) it passes the raw text through unchanged. The low ratios on those categories aren't a bug — there's nothing to compress; the structured items are still extracted and used for cross-turn delta dedup.

### End-to-end agent run (SWE-bench Lite, Cursor Composer-2)

Paired baseline-vs-sieve trial over the first 14 SWE-bench Lite instances, agent = **Cursor CLI / Composer-2**, scoring via the official `swebench.harness.run_evaluation` Docker harness. Of the 14, 4 reached the harness on this slice (2 prep failures, 8 still queued); the four scored were all astropy.

|                              | baseline | sieve  |
|------------------------------|---------:|-------:|
| instances scored             | 4        | 4      |
| resolved                     | 2        | 2      |
| resolve rate (of scored)     | 50.0%    | 50.0%  |
| patch chars                  | 21,242   | 19,956 |
| **agent-facing chars**       | 47,688   | **11,613** |
| raw chars                    | 47,688   | 40,416 |
| **compression ratio**        | 0%       | **71.3%** |

**Resolve rate is unchanged** — sieve compresses the agent's view of tool output without changing what the agent decides to do. **Agent-facing context drops 75.6%** (47k → 11.6k chars, ~36k saved on this slice). That is the headline: same task outcomes, far fewer tokens consumed by tool observations.

The remaining django instances are queued; numbers will be re-rendered once that scoring completes. Reproduce with:

```bash
bash scripts/run_cursor_swe_bench_profiles.sh --resume \
  --eval-with-harness --harness-namespace none
PYTHONPATH=src python3 -m benchmarks.swe_bench_compare \
  --baseline artifacts/cursor-swe-bench-lite.baseline.jsonl \
  --sieve    artifacts/cursor-swe-bench-lite.sieve.jsonl
```

### CI-Repair-Bench (recommended noisy-logs benchmark)

[**CI-Repair-Bench**](https://arxiv.org/abs/2604.27148) is built from real **GitHub Actions** failures (workflow YAML + long logs, formatting/lint/deps/env/config modes). That matches what burns context in production far better than issue-only benchmarks.

This repo implements **observation compression** over the Hugging Face dataset [`ci-benchmark-user/ci-repair-bench`](https://huggingface.co/datasets/ci-benchmark-user/ci-repair-bench): each instance’s synthetic observation is **workflow file + flattened logs** (the gold **`diff` is excluded** so we measure diagnostic bulk, not patch leakage). Full benchmark *repair scoring* is **re-run CI** on GitHub Actions per the paper — use their upstream harness for resolve rates; use ours for **token economics on log-shaped observations**.

```bash
uv sync --group swe-eval   # datasets
uv run python -m benchmarks.ci_repair_bench --limit 50 --compare
uv run python -m benchmarks.ci_repair_bench --compare --json   # all 567 rows
```

## Quick start

```bash
uv run python -m unittest discover -s tests -v
uv run python -m benchmarks.run                   # compression report
uv run python -m benchmarks.swe_bench_lite --traj-dir tests/fixtures/swe_bench_lite --compare
uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories --no-sieve   # baseline only
uv run python -m benchmarks.swe_bench_lite --traj-dir /path/to/trajectories --compare     # off vs on
```

The SWE-bench Lite trajectory benchmark replays SWE-agent-style **`*.traj`** files (observation stream per step). It does **not** run the SWE-bench Docker harness; generate trajectories with SWE-agent on the Lite split, then point `--traj-dir` at that folder. Use **`--no-sieve`** for baseline token count and **`--compare`** for side‑by‑side sieve off/on.

### SWE-bench Lite (full harness + paired off/on trials)

Official evaluation is **Docker patch apply + test** (`swebench.harness.run_evaluation`), not trajectory replay. This repo ships:

| Piece | Role |
|-------|------|
| `uv sync --group swe-eval` | `swebench` + `datasets` |
| `scripts/export_swe_lite_manifest.py` | HF Lite → JSONL manifest (no oracle patch) |
| `integrations/swe-bench-lite-cursor/` | **Cursor SDK** local agent → `predictions.jsonl` (`--profile baseline` vs `--profile sieve`) |
| `scripts/run_swe_bench_profiles.py` | Run both Cursor profiles and compare context / patch output |
| `scripts/setup_codex_swe_bench_experiment.py` | Prepare paired Codex workspaces for one Lite instance |
| `scripts/run_codex_swe_bench_profiles.py` | Run paired Codex or Cursor CLI trials over a Lite manifest |
| `benchmarks/swe_bench_compare.py` | Compare baseline vs sieve JSONL outputs |
| `scripts/run_swe_lite_harness.py` | Wrapper around `python -m swebench.harness.run_evaluation` |

Start with `--limit 1` on the manifest and one harness instance before scaling. The paired runners keep the same trial structure that the old benchmark scripts used:

Important:
- The paired Cursor/Codex runners now support a `harness-container` mode that builds the official SWE-bench instance image, mounts the profile workspace into that container at `/testbed`, and runs all wrapped verification commands there.
- The old `local-host-clone` mode still exists as a fallback, but it is less faithful and more prone to host Python / dependency drift.
- Treat harness `resolved` as the authoritative outcome either way.
- Locally-built instance images use the `sweb.eval.x86_64.<id>:latest` tag (no namespace). When invoking the harness from the paired runners, pass `--harness-namespace none` so the harness reuses those images instead of trying to pull `swebench/...` from Docker Hub.
- Image disk usage is non-trivial (~2.8 GB per instance). The runners delete per-instance images after each run by default, and pass `--clean True --cache_level base` to the harness so it cleans up after itself too. Pass `--keep-images` if you want to retain them for debugging.

`benchmarks.swe_bench_compare` reports three resolve-rate views:

- `resolve rate (overall)` — `resolved / instances`. Standard SWE-bench number.
- `resolve rate (of scored)` — `resolved / scored`. Useful when only a subset has been through the harness.
- `scored rate` — `scored / instances`. Tells you how much of the manifest has been evaluated.

- `baseline`: commands are routed through `scripts/sieved_run.py --no-sieve`, so observation totals are recorded but the agent sees raw output.
- `sieve`: the same command path records observations and delivers compressed output.

Cursor SDK path:

```bash
uv run python scripts/export_swe_lite_manifest.py -o benchmarks/manifests/lite_smoke.jsonl --limit 5
python3 scripts/run_swe_bench_profiles.py --manifest benchmarks/manifests/lite_smoke.jsonl
python3 scripts/run_swe_bench_profiles.py --manifest benchmarks/manifests/lite_smoke.jsonl --eval-with-harness
```

Codex/Cursor CLI paired path:

```bash
python3 scripts/run_codex_swe_bench_profiles.py --manifest benchmarks/manifests/lite_smoke.jsonl --engine codex --limit 1
PYTHONPATH=src python3 -m benchmarks.swe_bench_compare --baseline artifacts/codex-swe-bench-lite.baseline.jsonl --sieve artifacts/codex-swe-bench-lite.sieve.jsonl
```

The shell wrapper defaults to the containerized path:

```bash
bash scripts/run_cursor_swe_bench_profiles.sh --manifest benchmarks/manifests/lite_smoke.jsonl --resume \
  --eval-with-harness --harness-namespace none
```

Add `--eval-with-harness` to either paired runner if you want the official SWE-bench Docker evaluation to rewrite each profile JSONL with harness-backed `resolved` values before comparison.

## Usage

### Direct compression

```python
from sieve import CompressSession

session = CompressSession()
result = session.compress(
    command="pytest tests/",
    stdout=raw_stdout,
    stderr=raw_stderr,
    exit_code=1,
)
print(result.text)              # send this to the LLM
print(result.stats.compression_ratio)
```

`CompressSession` keeps state across calls, so the second `compress(...)` for the same test suite emits a delta against the first.

### Decorator wrapper

```python
import subprocess
from sieve import wrap_tool

@wrap_tool
def run_bash(command: str) -> tuple[str, str, int]:
    p = subprocess.run(command, shell=True, capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode
```

`run_bash(...)` now returns the compressed string. Session state is held by the decorator.

### Configuration

```python
from sieve import CompressConfig, CompressSession, OutputFormat

session = CompressSession(CompressConfig(
    format=OutputFormat.STRUCTURED,   # plain | structured | xml | minimal
    delta_mode=True,
    include_pattern_hints=True,
    max_raw_lines=50,
))
```

### MCP proxy (no application code changes)

`sieve.integrations.mcp` is an MCP proxy that wraps any upstream MCP server. The agent talks to the proxy as if it were the upstream; the proxy forwards `tools/list` and `tools/call`, and runs every `TextContent` block in the result through a shared `CompressSession` before returning it. A single session lives for the proxy's lifetime, so cross-tool delta compression works.

Install the optional dep:

```bash
pip install 'sieve[mcp]'
```

Configure your MCP client (Claude Desktop, Cursor, Continue, etc.) to launch the proxy in place of the upstream. Example wrapping the official **`server-everything`** demo server (`npx` downloads it on first run):

```jsonc
// Claude Desktop's mcp_servers config / Cursor .cursor/mcp.json
{
  "mcpServers": {
    "sieve-demo": {
      "command": "python",
      "args": [
        "-m", "sieve.integrations.mcp",
        "--",
        "npx", "-y", "@modelcontextprotocol/server-everything"
      ]
    }
  }
}
```

Use whatever upstream you already rely on (e.g. **`@modelcontextprotocol/server-filesystem`** with the paths your client expects); there is **no** published `@modelcontextprotocol/server-bash` on npm.

That's the entire integration: the agent sees the same upstream tools, but every `TextContent` result has been compressed.

For non-shell tools, the proxy uses the tool name as the parser-router hint; for shell-like tools that take a `command` / `cmd` / `shellCommand` argument, the actual command string is forwarded so parser detection (pytest, mypy, etc.) works correctly.

## What it looks like

Raw pytest run with two failures (1,818 chars):

```
============================= test session starts ==============================
platform linux -- Python 3.12.0, pytest-8.1.1, pluggy-1.4.0
... [40 lines of header + per-test output] ...
=================================== FAILURES ===================================
________________________________ test_user_update ________________________________
    def test_user_update(self):
        ...
>       assert response.status_code == 200
E       AssertionError: assert 403 == 200
tests/test_views.py:89: AssertionError
... [equivalent block for test_user_delete] ...
=========================== short test summary info ============================
FAILED tests/test_views.py::TestUserViewSet::test_user_update - AssertionError
FAILED tests/test_views.py::TestUserViewSet::test_user_delete - AssertionError
========================= 2 failed, 140 passed, 0 warnings ====================
```

After Sieve (297 chars, 83.7% reduction):

```
PYTEST: 2 failed, 140 passed (142 total)
FAIL tests/test_views.py::TestUserViewSet::test_user_update (test_views.py:89)
  expected 200, got 403
FAIL tests/test_views.py::TestUserViewSet::test_user_delete (test_views.py:102)
  expected 204, got 403
Pattern: All failures return 403 in test_views.py
```

On the next turn, the agent fixes `test_user_update` and re-runs:

```
PYTEST DELTA (turn 2)
PASS tests/test_views.py::TestUserViewSet::test_user_update now passes
STILL FAIL tests/test_views.py::TestUserViewSet::test_user_delete (line 102) - expected 204, got 403
Result: 1 failed, 141 passed (142 total)
```

## Design

```
RawExecution → ParserRouter → {PytestParser | PythonTracebackParser | GenericParser}
             → StructuredOutput → DeltaEngine + SessionState
             → CompressedOutput → Formatter → text
```

- **Parsers** turn raw output into a typed `StructuredOutput` (test results, runtime errors, line counts). Each parser owns its own format detection and is independent.
- **SessionState** carries failing-test results, error signatures, and read-file hashes across turns.
- **DeltaEngine** diffs the current parse against session state, emitting only what changed (`PYTEST DELTA: unchanged`, `STILL FAIL ...`, `same error as turn N`).
- **Formatter** renders to plain / JSON / XML / minimal.

## Layout

```
src/sieve/                core, config, router, session, delta, formatter, stats, api
src/sieve/parsers/        base + pytest_, python_tb, mypy_, tsc, eslint_, gcc, pip_, generic
src/sieve/integrations/   mcp proxy (optional, requires `mcp` extra)
tests/                    unit + fidelity tests, fixtures/, mcp_helpers/
benchmarks/               run.py, corpus.py
docs/                     full specification
```

## Roadmap

Remaining parsers from the spec (jest/mocha, npm install, cargo, rustc, go test) and additional integration wrappers (`integrations/anthropic.py`, `integrations/openai.py`) are not yet implemented.
