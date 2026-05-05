#!/usr/bin/env python3
"""Run SWE-bench Lite Codex/Cursor experiments with sieve off/on and compare results."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from benchmarks.swe_bench_compare import compare_rows, load_rows, render_text
from scripts.setup_codex_swe_bench_experiment import (
    HARNESS_CONTAINER,
    LOCAL_HOST_CLONE,
    ManifestRow,
    ProfileLayout,
    experiment_root,
    prepare_instance,
    profile_container_name,
    slugify_instance,
)
from scripts.swe_bench_harness_results import (
    load_resolved_ids,
    merge_resolved_into_jsonl,
    run_harness,
)

RUNNER_SIGNATURE = "swe-lite-runner-v3"
DEFAULT_CONTAINER_WORK_ROOT = Path("/tmp/agent_compress_swe_workspaces")


@dataclass(frozen=True)
class RunArtifacts:
    events_jsonl: Path
    stderr_log: Path
    final_message: Path
    diff_patch: Path


def load_manifest(path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        rows.append(
            ManifestRow(
                instance_id=str(obj["instance_id"]),
                repo=str(obj["repo"]),
                base_commit=str(obj["base_commit"]),
                problem_statement=str(obj["problem_statement"]),
                extra={
                    key: value
                    for key, value in obj.items()
                    if key not in {"instance_id", "repo", "base_commit", "problem_statement"}
                },
            )
        )
    return rows


def enrich_manifest_rows(
    rows: list[ManifestRow],
    *,
    dataset: str,
    split: str,
) -> list[ManifestRow]:
    required = {"version", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"}
    if not any(not required.issubset(set((row.extra or {}).keys())) for row in rows):
        return rows

    from datasets import load_dataset

    dataset_rows = load_dataset(dataset, split=split)
    by_instance = {str(item["instance_id"]): item for item in dataset_rows}
    enriched: list[ManifestRow] = []
    for row in rows:
        extra = dict(row.extra or {})
        if required.issubset(set(extra.keys())):
            enriched.append(row)
            continue
        source = by_instance.get(row.instance_id)
        if source is None:
            raise RuntimeError(f"instance {row.instance_id} not found in dataset {dataset} split {split}")
        merged_extra = dict(extra)
        for key in (
            "version",
            "test_patch",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "environment_setup_commit",
            "hints_text",
        ):
            if key not in merged_extra and key in source:
                merged_extra[key] = source[key]
        enriched.append(
            ManifestRow(
                instance_id=row.instance_id,
                repo=row.repo,
                base_commit=row.base_commit,
                problem_statement=row.problem_statement,
                extra=merged_extra,
            )
        )
    return enriched


def _profile_results_path(results_dir: Path, profile: str, engine: str = "codex") -> Path:
    prefix = "codex-swe-bench-lite" if engine == "codex" else f"{engine}-swe-bench-lite"
    return results_dir / f"{prefix}.{profile}.jsonl"


def _run_artifact_dir(results_dir: Path, instance_id: str, profile: str, engine: str = "codex") -> Path:
    subdir = "codex-runs" if engine == "codex" else f"{engine}-runs"
    return results_dir / subdir / slugify_instance(instance_id) / profile


def build_codex_command(
    *,
    layout: ProfileLayout,
    artifacts: RunArtifacts,
    model: str | None,
    sandbox: str,
    ephemeral: bool,
) -> list[str]:
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(layout.workspace),
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "--full-auto",
        "--add-dir",
        str(layout.profile_root.parent),
        "--json",
        "--output-last-message",
        str(artifacts.final_message),
    ]
    if model:
        cmd.extend(["--model", model])
    if ephemeral:
        cmd.append("--ephemeral")
    cmd.append("-")
    return cmd


def build_cursor_command(*, layout: ProfileLayout, model: str | None) -> list[str]:
    cmd = [
        "cursor-agent",
        "-p",
        "--output-format",
        "stream-json",
        "--force",
        "--trust",
        "--sandbox",
        "disabled",
        "--workspace",
        str(layout.workspace),
    ]
    if model:
        cmd.extend(["--model", model])
    return cmd


def detect_agent_failure(*, engine: str, events_jsonl: Path, exit_code: int) -> str | None:
    if not events_jsonl.is_file():
        if exit_code != 0:
            return f"agent exited {exit_code} with no events"
        return None

    last_result: dict[str, Any] | None = None
    for line in events_jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = obj.get("type")
        if engine == "codex":
            if kind == "error":
                return f"codex_error: {str(obj.get('message', 'codex error'))[:200]}"
            if kind == "turn.failed":
                err = (obj.get("error") or {}).get("message", "turn failed")
                return f"codex_turn_failed: {str(err)[:200]}"
        elif engine == "cursor" and kind == "result":
            last_result = obj

    if engine == "cursor":
        if last_result is None:
            return f"cursor_no_result (exit={exit_code})"
        if last_result.get("is_error"):
            return f"cursor_error: {str(last_result.get('result', 'cursor reported error'))[:200]}"

    if exit_code != 0:
        return f"{engine}_exit_{exit_code}"
    return None


def aggregate_context(run_dir: Path) -> dict[str, int]:
    raw_chars = 0
    agent_chars = 0
    saved_chars = 0
    for meta_path in sorted(run_dir.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw_chars += int(meta.get("raw_chars", 0))
        agent_chars += int(meta.get("agent_chars", 0))
        saved_chars += int(meta.get("saved_chars", 0))
    return {
        "raw_chars": raw_chars,
        "agent_chars": agent_chars,
        "saved_chars": saved_chars,
    }


def extract_patch(workspace: Path) -> str:
    import os

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    git_prefix = ["git", "-c", "core.excludesFile=/dev/null", "-C", str(workspace)]
    subprocess.run([*git_prefix, "add", "-A"], capture_output=True, text=True, env=env)
    subprocess.run(
        [*git_prefix, "reset", "--quiet", "--", "CODEX_PROMPT.txt"],
        capture_output=True,
        text=True,
        env=env,
    )
    proc = subprocess.run(
        [*git_prefix, "diff", "--cached"],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout


def append_result(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _result_matches_current_runner(row: dict[str, Any], environment_mode: str) -> bool:
    return (
        row.get("runner_signature") == RUNNER_SIGNATURE
        and row.get("environment_mode") == environment_mode
    )


def compare_profile_outputs(results_dir: Path, engine: str = "codex") -> dict[str, Any]:
    baseline_path = _profile_results_path(results_dir, "baseline", engine)
    sieve_path = _profile_results_path(results_dir, "sieve", engine)
    return compare_rows(load_rows(baseline_path), load_rows(sieve_path))


def run_agent(
    *,
    engine: str,
    layout: ProfileLayout,
    artifacts: RunArtifacts,
    model: str | None,
    sandbox: str,
    ephemeral: bool,
) -> int:
    if engine == "codex":
        cmd = build_codex_command(
            layout=layout,
            artifacts=artifacts,
            model=model,
            sandbox=sandbox,
            ephemeral=ephemeral,
        )
    elif engine == "cursor":
        cmd = build_cursor_command(layout=layout, model=model)
    else:
        raise ValueError(f"unknown engine: {engine}")

    artifacts.events_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with (
        layout.prompt_file.open("r", encoding="utf-8") as prompt_file,
        artifacts.events_jsonl.open("w", encoding="utf-8") as stdout_file,
        artifacts.stderr_log.open("w", encoding="utf-8") as stderr_file,
    ):
        proc = subprocess.run(
            cmd,
            stdin=prompt_file,
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=ROOT,
            text=True,
        )
    if engine == "cursor":
        last_text = ""
        for line in artifacts.events_jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "result" and obj.get("result"):
                last_text = str(obj["result"])
        if last_text:
            artifacts.final_message.write_text(last_text, encoding="utf-8")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--work-root", type=Path, default=DEFAULT_CONTAINER_WORK_ROOT)
    parser.add_argument("--engine", choices=("cursor", "codex"), default="codex")
    parser.add_argument("--model")
    parser.add_argument("--sandbox", default="workspace-write")
    parser.add_argument(
        "--environment-mode",
        choices=(LOCAL_HOST_CLONE, HARNESS_CONTAINER),
        default=HARNESS_CONTAINER,
    )
    parser.add_argument("--instance-dataset", default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--instance-split", default="test")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--ephemeral", action="store_true")
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Keep instance Docker images after each run. Default: remove them to reclaim disk.",
    )
    parser.add_argument("--eval-with-harness", action="store_true")
    parser.add_argument(
        "--harness-dataset",
        default="princeton-nlp/SWE-bench_Lite",
        help="Dataset passed to the official SWE-bench harness.",
    )
    parser.add_argument("--harness-split", default="test")
    parser.add_argument("--harness-max-workers", type=int, default=4)
    parser.add_argument(
        "--harness-report-dir",
        type=Path,
        default=ROOT / "artifacts" / "harness-reports",
    )
    parser.add_argument(
        "--harness-namespace",
        default=None,
        help="Image namespace for the harness ('none' to use locally-built images, 'swebench' for Docker Hub).",
    )
    parser.add_argument(
        "--mode",
        choices=("run", "compare-only"),
        default="run",
        help="Run both profiles then compare, or only compare existing JSONL outputs.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        print(f"missing manifest: {args.manifest}", file=sys.stderr)
        return 2

    args.results_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "run":
        rows = load_manifest(args.manifest.resolve())
        rows = enrich_manifest_rows(
            rows,
            dataset=args.instance_dataset,
            split=args.instance_split,
        )
        if args.limit > 0:
            rows = rows[: args.limit]

        completed_ids: dict[str, set[str]] = {"baseline": set(), "sieve": set()}
        if args.resume:
            for profile in completed_ids:
                result_path = _profile_results_path(args.results_dir.resolve(), profile, args.engine)
                if result_path.exists():
                    completed_ids[profile] = {
                        str(item["instance_id"])
                        for item in load_rows(result_path)
                        if "instance_id" in item
                        and not item.get("error")
                        and _result_matches_current_runner(item, args.environment_mode)
                    }

        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            if args.resume and all(row.instance_id in completed_ids[p] for p in ("baseline", "sieve")):
                print(f"[{idx}/{total}] skip (resume): {row.instance_id}", flush=True)
                continue

            print(f"[{idx}/{total}] preparing: {row.instance_id}", flush=True)
            try:
                layouts = prepare_instance(
                    row=row,
                    work_root=args.work_root.resolve(),
                    repo_root=ROOT,
                    force=True,
                    environment_mode=args.environment_mode,
                    dataset=args.instance_dataset,
                    split=args.instance_split,
                )
            except Exception as exc:
                print(f"[{idx}/{total}] PREPARE FAILED for {row.instance_id}: {exc}", file=sys.stderr, flush=True)
                for profile in ("baseline", "sieve"):
                    append_result(
                        _profile_results_path(args.results_dir.resolve(), profile, args.engine),
                        {
                            "instance_id": row.instance_id,
                            "repo": row.repo,
                            "base_commit": row.base_commit,
                            "profile": profile,
                            "environment_mode": args.environment_mode,
                            "runner_signature": RUNNER_SIGNATURE,
                            "resolved": None,
                            "harness": {"status": "not_run"},
                            "has_patch": False,
                            "model_patch": "",
                            "error": f"prepare_failed: {exc}",
                        },
                    )
                continue

            for profile, layout in layouts.items():
                if args.resume and row.instance_id in completed_ids[profile]:
                    continue
                artifact_dir = _run_artifact_dir(args.results_dir.resolve(), row.instance_id, profile, args.engine)
                artifacts = RunArtifacts(
                    events_jsonl=artifact_dir / "events.jsonl",
                    stderr_log=artifact_dir / "stderr.log",
                    final_message=artifact_dir / "final.md",
                    diff_patch=artifact_dir / "diff.patch",
                )
                print(f"[{idx}/{total}]   running {profile}", flush=True)
                try:
                    agent_exit = run_agent(
                        engine=args.engine,
                        layout=layout,
                        artifacts=artifacts,
                        model=args.model,
                        sandbox=args.sandbox,
                        ephemeral=args.ephemeral,
                    )
                    agent_failure = detect_agent_failure(
                        engine=args.engine,
                        events_jsonl=artifacts.events_jsonl,
                        exit_code=agent_exit,
                    )
                    patch = extract_patch(layout.workspace)
                    artifacts.diff_patch.write_text(patch, encoding="utf-8")
                    context = aggregate_context(layout.run_dir)
                    append_result(
                        _profile_results_path(args.results_dir.resolve(), profile, args.engine),
                        {
                            "instance_id": row.instance_id,
                            "repo": row.repo,
                            "base_commit": row.base_commit,
                            "profile": profile,
                            "workspace": str(layout.workspace),
                            "environment_mode": args.environment_mode,
                            "runner_signature": RUNNER_SIGNATURE,
                            "container_name": profile_container_name(layout)
                            if args.environment_mode == HARNESS_CONTAINER
                            else None,
                            "model_name_or_path": f"{args.engine}-{profile}",
                            "model_patch": patch,
                            "has_patch": bool(patch.strip()),
                            "resolved": None,
                            "context": context,
                            "harness": {"status": "not_run"},
                            "agent": {
                                "exit_code": agent_exit,
                                "events_jsonl": str(artifacts.events_jsonl),
                                "stderr_log": str(artifacts.stderr_log),
                                "final_message": str(artifacts.final_message),
                            },
                            "diff": {"patch_path": str(artifacts.diff_patch)},
                            "error": agent_failure,
                        },
                    )
                except Exception as exc:
                    append_result(
                        _profile_results_path(args.results_dir.resolve(), profile, args.engine),
                        {
                            "instance_id": row.instance_id,
                            "repo": row.repo,
                            "base_commit": row.base_commit,
                            "profile": profile,
                            "workspace": str(layout.workspace),
                            "environment_mode": args.environment_mode,
                            "runner_signature": RUNNER_SIGNATURE,
                            "container_name": profile_container_name(layout)
                            if args.environment_mode == HARNESS_CONTAINER
                            else None,
                            "model_name_or_path": f"{args.engine}-{profile}-error",
                            "model_patch": "",
                            "has_patch": False,
                            "resolved": None,
                            "harness": {"status": "not_run"},
                            "error": f"run_failed: {exc}",
                        },
                    )

            if not args.keep_workspaces:
                if args.environment_mode == HARNESS_CONTAINER:
                    for layout in layouts.values():
                        subprocess.run(
                            ["docker", "rm", "-f", profile_container_name(layout)],
                            capture_output=True,
                            text=True,
                        )
                instance_root = experiment_root(args.work_root.resolve(), row.instance_id)
                if instance_root.exists():
                    shutil.rmtree(instance_root, ignore_errors=True)

            if (
                not args.keep_images
                and not args.eval_with_harness
                and args.environment_mode == HARNESS_CONTAINER
            ):
                instance_image = f"sweb.eval.x86_64.{row.instance_id.lower()}:latest"
                subprocess.run(
                    ["docker", "rmi", "-f", instance_image],
                    capture_output=True,
                    text=True,
                )

    if args.eval_with_harness:
        for profile in ("baseline", "sieve"):
            predictions_path = _profile_results_path(args.results_dir.resolve(), profile, args.engine)
            if not predictions_path.is_file():
                continue
            run_id = f"{args.engine}-swe-bench-lite-{profile}"
            report_dir = args.harness_report_dir.resolve() / run_id
            code, summary_report = run_harness(
                predictions_path=predictions_path,
                run_id=run_id,
                dataset=args.harness_dataset,
                split=args.harness_split,
                report_dir=report_dir,
                max_workers=args.harness_max_workers,
                namespace=args.harness_namespace,
                clean=not args.keep_images,
                cache_level="base" if not args.keep_images else None,
            )
            if code != 0:
                print(
                    f"harness evaluation failed for {profile}; leaving resolved fields unchanged",
                    file=sys.stderr,
                )
                continue
            if summary_report is None:
                print(
                    f"harness evaluation for {profile} produced no summary report",
                    file=sys.stderr,
                )
                continue
            merge_resolved_into_jsonl(
                predictions_path=predictions_path,
                resolved_ids=load_resolved_ids(summary_report),
                summary_report=summary_report,
                run_id=run_id,
            )

    report = compare_profile_outputs(args.results_dir.resolve(), args.engine)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
