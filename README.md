# Sieve

Transparent feedback compression middleware for LLM coding agents. Sieve sits between an agent and its tools, parsing tool output and emitting a compact form before it enters the conversation context.

83.9% of tokens in coding-agent trajectories are tool observations (JetBrains, NeurIPS 2025). Most of those are re-read on every subsequent turn. Sieve targets that bloat by parsing — not truncating — the output of common dev tools, then diffing against prior turns so the agent only sees what changed.

Full design in [`docs/agent-compress-specs.md`](docs/agent-compress-specs.md).

## What's in the box

| | |
|--|--|
| Parsers | pytest, Python traceback, mypy, tsc, eslint, gcc/clang, pip, generic fallback |
| Output formats | plain, structured (JSON), XML, minimal |
| Integrations | MCP proxy, SWE-bench Lite paired Cursor / Codex runners |
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

Paired baseline-vs-sieve trial with **Cursor CLI / Composer-2**, scored by the official `swebench.harness.run_evaluation` Docker harness.

|                              | baseline | sieve  |
|------------------------------|---------:|-------:|
| instances scored             | 4        | 4      |
| resolved                     | 2        | 2      |
| resolve rate (of scored)     | 50.0%    | 50.0%  |
| patch chars                  | 21,242   | 19,956 |
| **agent-facing chars**       | 47,688   | **11,613** |
| raw chars                    | 47,688   | 40,416 |
| **compression ratio**        | 0%       | **71.3%** |

**Resolve rate is unchanged** and **agent-facing context drops 75.6%** (47k → 11.6k chars). Reproduce with:

```bash
bash scripts/run_cursor_swe_bench_profiles.sh --resume \
  --eval-with-harness --harness-namespace none
PYTHONPATH=src python3 -m benchmarks.swe_bench_compare \
  --baseline artifacts/cursor-swe-bench-lite.baseline.jsonl \
  --sieve    artifacts/cursor-swe-bench-lite.sieve.jsonl
```

### CI-Repair-Bench (noisy-logs benchmark)

[**CI-Repair-Bench**](https://arxiv.org/abs/2604.27148) is built from real GitHub Actions failures (workflow YAML + long logs). We measure observation compression over the [`ci-benchmark-user/ci-repair-bench`](https://huggingface.co/datasets/ci-benchmark-user/ci-repair-bench) dataset; each observation is workflow + flattened logs with the gold diff excluded, so the metric is diagnostic bulk, not patch leakage. For repair scoring use the paper's upstream harness.

```bash
uv sync --group swe-eval   # datasets
uv run python -m benchmarks.ci_repair_bench --compare --json   # all 567 rows
```

## Quick start

```bash
uv run python -m unittest discover -s tests -v
uv run python -m benchmarks.run                   # compression report on fixture corpus
```

### SWE-bench Lite (paired baseline-vs-sieve trials)

Wraps the official `swebench.harness.run_evaluation` Docker harness. The paired runner builds each instance's `harness-container`, mounts the workspace at `/testbed`, runs the agent, and emits a `predictions.jsonl` per profile. The harness then rewrites each row with the authoritative `resolved` value.

```bash
uv sync --group swe-eval

bash scripts/run_cursor_swe_bench_profiles.sh \
  --manifest benchmarks/manifests/lite_smoke.jsonl \
  --resume --eval-with-harness --harness-namespace none

PYTHONPATH=src python3 -m benchmarks.swe_bench_compare \
  --baseline artifacts/cursor-swe-bench-lite.baseline.jsonl \
  --sieve    artifacts/cursor-swe-bench-lite.sieve.jsonl
```

Notes:
- `--harness-namespace none` reuses locally-built `sweb.eval.x86_64.<id>:latest` images instead of pulling `swebench/...` from Docker Hub.
- The runner deletes per-instance images and workspaces after each row, and passes `--clean True --cache_level base` to the harness. Pass `--keep-images` / `--keep-workspaces` to retain them.
- Swap `cursor` for `codex` in the script name to use the Codex CLI agent instead.
- The trajectory-only variant (`benchmarks.swe_bench_lite`, replays `*.traj` files for token counts without re-running tests) is still available; it does not run the harness.

`benchmarks.swe_bench_compare` reports three resolve-rate views: overall (`resolved / instances`), of-scored (`resolved / scored`), and scored-rate (`scored / instances`).

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
