#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE=cursor bash "$ROOT/scripts/run_codex_swe_bench_profiles.sh" "$@"
