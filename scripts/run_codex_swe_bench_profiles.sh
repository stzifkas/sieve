#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST=""
RESULTS_DIR="$ROOT/artifacts"
WORK_ROOT="${WORK_ROOT:-/tmp/agent_compress_swe_workspaces}"
ENGINE="${ENGINE:-cursor}"
MODEL="${MODEL:-}"
SANDBOX="${SANDBOX:-workspace-write}"
ENVIRONMENT_MODE="${ENVIRONMENT_MODE:-harness-container}"
INSTANCE_DATASET="${INSTANCE_DATASET:-princeton-nlp/SWE-bench_Lite}"
INSTANCE_SPLIT="${INSTANCE_SPLIT:-test}"
LIMIT="${LIMIT:-0}"
MODE="${MODE:-run}"
MANIFEST_LIMIT="${MANIFEST_LIMIT:-10}"
SPLIT="${SPLIT:-test}"
HARNESS_DATASET="${HARNESS_DATASET:-princeton-nlp/SWE-bench_Lite}"
HARNESS_SPLIT="${HARNESS_SPLIT:-test}"
HARNESS_MAX_WORKERS="${HARNESS_MAX_WORKERS:-4}"
HARNESS_REPORT_DIR="${HARNESS_REPORT_DIR:-$ROOT/artifacts/harness-reports}"
HARNESS_NAMESPACE="${HARNESS_NAMESPACE:-}"
JSON=0
RESUME=0
EPHEMERAL=0
KEEP_WORKSPACES=0
KEEP_IMAGES=0
EVAL_WITH_HARNESS=0

usage() {
  cat <<EOF
Runs the SWE-bench Lite baseline/sieve benchmark end-to-end.

Usage:
  $(basename "$0") [--manifest PATH] [options]

Options:
  --manifest PATH        SWE-bench Lite manifest JSONL. If omitted, auto-generate one.
  --results-dir PATH     Output JSONL/artifacts root. Default: $RESULTS_DIR
  --work-root PATH       Workspace root for prepared Lite checkouts. Default: $WORK_ROOT
  --engine NAME          cursor (default) or codex.
  --model NAME           Agent model override.
  --sandbox NAME         Codex sandbox mode. Default: $SANDBOX
  --environment-mode STR local-host-clone or harness-container. Default: $ENVIRONMENT_MODE
  --instance-dataset STR Dataset used to hydrate/build instance environments. Default: $INSTANCE_DATASET
  --instance-split STR   Split used to hydrate/build instance environments. Default: $INSTANCE_SPLIT
  --limit N              Limit instances. Default: $LIMIT
  --mode NAME            run (default) or compare-only.
  --manifest-limit N     Auto-generated manifest size when --manifest is omitted. Default: $MANIFEST_LIMIT
  --split NAME           Dataset split for auto-generated manifest. Default: $SPLIT
  --resume               Skip instances already present in both profile outputs.
  --eval-with-harness    Run official SWE-bench harness after baseline/sieve generation.
  --harness-dataset STR  Harness dataset id. Default: $HARNESS_DATASET
  --harness-split STR    Harness split. Default: $HARNESS_SPLIT
  --harness-max-workers N  Harness parallelism. Default: $HARNESS_MAX_WORKERS
  --harness-report-dir PATH Harness summary output dir. Default: $HARNESS_REPORT_DIR
  --harness-namespace STR  Harness image namespace ("none" for locally-built images, "swebench" for Docker Hub).
  --ephemeral            Pass --ephemeral to codex exec.
  --keep-workspaces      Keep per-instance workspaces after runs.
  --keep-images          Keep per-instance Docker images after runs (default: remove to save disk).
  --json                 Emit JSON report.
  -h, --help             Show help.

Example:
  $(basename "$0") --manifest benchmarks/manifests/lite_smoke.jsonl --resume
  $(basename "$0") --manifest-limit 25 --resume
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST="$2"
      shift 2
      ;;
    --results-dir)
      RESULTS_DIR="$2"
      shift 2
      ;;
    --work-root)
      WORK_ROOT="$2"
      shift 2
      ;;
    --engine)
      ENGINE="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --sandbox)
      SANDBOX="$2"
      shift 2
      ;;
    --environment-mode)
      ENVIRONMENT_MODE="$2"
      shift 2
      ;;
    --instance-dataset)
      INSTANCE_DATASET="$2"
      shift 2
      ;;
    --instance-split)
      INSTANCE_SPLIT="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --manifest-limit)
      MANIFEST_LIMIT="$2"
      shift 2
      ;;
    --split)
      SPLIT="$2"
      shift 2
      ;;
    --resume)
      RESUME=1
      shift
      ;;
    --eval-with-harness)
      EVAL_WITH_HARNESS=1
      shift
      ;;
    --harness-dataset)
      HARNESS_DATASET="$2"
      shift 2
      ;;
    --harness-split)
      HARNESS_SPLIT="$2"
      shift 2
      ;;
    --harness-max-workers)
      HARNESS_MAX_WORKERS="$2"
      shift 2
      ;;
    --harness-report-dir)
      HARNESS_REPORT_DIR="$2"
      shift 2
      ;;
    --harness-namespace)
      HARNESS_NAMESPACE="$2"
      shift 2
      ;;
    --ephemeral)
      EPHEMERAL=1
      shift
      ;;
    --keep-workspaces)
      KEEP_WORKSPACES=1
      shift
      ;;
    --keep-images)
      KEEP_IMAGES=1
      shift
      ;;
    --json)
      JSON=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$MANIFEST" ]]; then
  MANIFEST="$ROOT/benchmarks/manifests/swe_bench_lite_auto_${SPLIT}_${MANIFEST_LIMIT}.jsonl"
  echo "auto-generating manifest: $MANIFEST" >&2
  python3 "$ROOT/scripts/export_swe_lite_manifest.py" \
    --output "$MANIFEST" \
    --split "$SPLIT" \
    --limit "$MANIFEST_LIMIT"
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "missing manifest: $MANIFEST" >&2
  exit 2
fi

CMD=(
  python3
  "$ROOT/scripts/run_codex_swe_bench_profiles.py"
  --manifest "$MANIFEST"
  --results-dir "$RESULTS_DIR"
  --work-root "$WORK_ROOT"
  --engine "$ENGINE"
  --sandbox "$SANDBOX"
  --environment-mode "$ENVIRONMENT_MODE"
  --instance-dataset "$INSTANCE_DATASET"
  --instance-split "$INSTANCE_SPLIT"
  --limit "$LIMIT"
  --mode "$MODE"
)

if [[ -n "$MODEL" ]]; then
  CMD+=(--model "$MODEL")
fi
if [[ "$RESUME" -eq 1 ]]; then
  CMD+=(--resume)
fi
if [[ "$EVAL_WITH_HARNESS" -eq 1 ]]; then
  CMD+=(
    --eval-with-harness
    --harness-dataset "$HARNESS_DATASET"
    --harness-split "$HARNESS_SPLIT"
    --harness-max-workers "$HARNESS_MAX_WORKERS"
    --harness-report-dir "$HARNESS_REPORT_DIR"
  )
  if [[ -n "$HARNESS_NAMESPACE" ]]; then
    CMD+=(--harness-namespace "$HARNESS_NAMESPACE")
  fi
fi
if [[ "$EPHEMERAL" -eq 1 ]]; then
  CMD+=(--ephemeral)
fi
if [[ "$KEEP_WORKSPACES" -eq 1 ]]; then
  CMD+=(--keep-workspaces)
fi
if [[ "$KEEP_IMAGES" -eq 1 ]]; then
  CMD+=(--keep-images)
fi
if [[ "$JSON" -eq 1 ]]; then
  CMD+=(--json)
fi

cd "$ROOT"
PYTHONPATH=src:. "${CMD[@]}"
