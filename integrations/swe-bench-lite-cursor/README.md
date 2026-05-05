# SWE-bench Lite × Cursor SDK

End-to-end path:

1. **Manifest** — JSONL of `instance_id`, `repo`, `base_commit`, `problem_statement` (no oracle patch).
2. **Generate predictions** — this tool clones each repo at `base_commit`, runs a **local** Cursor agent (`Agent.prompt`), then records **`git diff --cached`** as `model_patch`.
3. **Harness** — official `swebench.harness.run_evaluation` (Docker) scores patches against Lite tests.

Important: the TypeScript Cursor SDK path here still runs the agent in a **local host clone**. The paired Python runner under `scripts/run_cursor_swe_bench_profiles.sh` now supports a more faithful `harness-container` mode for command execution. In either case, use harness `resolved` as the authoritative score.

## Prereqs

- Docker (for step 3 only)
- `git`, Node 18+, `npm`
- Machine where **`@cursor/sdk` local agents actually run** (Cursor CLI / local runtime — see [SDK docs](https://cursor.com/docs/api/sdk/typescript))
- `CURSOR_API_KEY` ([dashboard](https://cursor.com/dashboard/cloud-agents))
- `uv` on PATH (used by both profiles to route noisy shell commands through `scripts/sieved_run.py`)

```bash
# Python deps for manifest export + harness
cd ../..   # repo root
uv sync --group swe-eval

# TS deps
cd integrations/swe-bench-lite-cursor
npm install
```

## 1. Export manifest (subset or full Lite test split)

```bash
cd ../..   # repo root
uv run python scripts/export_swe_lite_manifest.py -o benchmarks/manifests/lite_n.jsonl --limit 10
```

## 2a. Baseline agent

Baseline still injects the same Shell hook, but sets `SIEVE_NO_SIEVE=1`. That keeps workspace setup and command routing identical to the sieve trial while preserving raw agent-visible output.

```bash
export CURSOR_API_KEY=cursor_...
cd integrations/swe-bench-lite-cursor
npx tsx src/run.ts \
  --manifest ../../benchmarks/manifests/lite_n.jsonl \
  --predictions ../../artifacts/lite.cursor.baseline.jsonl \
  --profile baseline
```

## 2b. Sieve-assisted agent

Injects `.cursor/hooks.json` into each clone so **`preToolUse` Shell** rewrites noisy commands through `scripts/sieved_run.py` in **this** repo (requires `python3` + `uv`).

```bash
npx tsx src/run.ts \
  --manifest ../../benchmarks/manifests/lite_n.jsonl \
  --predictions ../../artifacts/lite.cursor.sieve.jsonl \
  --profile sieve
```

Flags: `--limit N`, `--resume` (skip `instance_id` already present in predictions file), `--model composer-2`, `--keep-workspaces`.

Workspaces live under **`<repo>/.swe-workspaces/<instance>/<profile>/workspace`** and each profile records `.sieve/runs/*.meta.json` plus a `session.json` sidecar.

## 3. Run official Lite harness

```bash
cd ../..   # repo root
uv run python scripts/run_swe_lite_harness.py \
  --predictions artifacts/lite.cursor.baseline.jsonl \
  --run-id cursor-lite-baseline-001

uv run python scripts/run_swe_lite_harness.py \
  --predictions artifacts/lite.cursor.sieve.jsonl \
  --run-id cursor-lite-sieve-001
```

Use harness `--report_dir` if you want JSON summaries in a fixed folder; compare **resolved** counts between baseline vs sieve runs.

## Caveats

- **Cost/time**: full Lite = 300 Docker evaluations × clone time × agent wall-clock; start with `--limit 1–5`.
- **Empty patches**: failed runs still emit a JSONL row with `model_patch: ""` so you can resume.
- **GitHub**: set `GITHUB_TOKEN` if you hit clone rate limits.
- **Harness ≠ trajectory replay**: `benchmarks/swe_bench_lite.py` scores observation compression on `.traj` files; this README is the **patch submission** path.
