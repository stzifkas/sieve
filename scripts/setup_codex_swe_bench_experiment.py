#!/usr/bin/env python3
"""Prepare paired SWE-bench Lite workspaces for Codex sieve-off/on experiments."""

from __future__ import annotations

import argparse
import json
import os
import sys
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.swebench_env import resolve_eval_python


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ManifestRow:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    extra: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProfileLayout:
    name: str
    profile_root: Path
    workspace: Path
    deps_dir: Path
    run_dir: Path
    session_file: Path
    prompt_file: Path
    bootstrap_log: Path


LOCAL_HOST_CLONE = "local-host-clone"
HARNESS_CONTAINER = "harness-container"


def slugify_instance(instance_id: str) -> str:
    return instance_id.replace("/", "__")


def experiment_root(work_root: Path, instance_id: str) -> Path:
    return work_root / slugify_instance(instance_id)


def manifest_row_payload(row: ManifestRow) -> dict[str, Any]:
    payload = {
        "instance_id": row.instance_id,
        "repo": row.repo,
        "base_commit": row.base_commit,
        "problem_statement": row.problem_statement,
    }
    if row.extra:
        payload.update(row.extra)
    return payload


def profile_container_name(layout: ProfileLayout) -> str:
    slug = layout.profile_root.parent.name.lower()
    return f"sweb.agent.{slug}.{layout.name}"


def container_runtime_root(layout: ProfileLayout) -> Path:
    return Path("/tmp/agent_compress_swebench_runtime") / layout.profile_root.parent.name / layout.name


def build_layouts(instance_root: Path) -> dict[str, ProfileLayout]:
    layouts: dict[str, ProfileLayout] = {}
    for name in ("baseline", "sieve"):
        profile_root = instance_root / name
        workspace = profile_root / "workspace"
        layouts[name] = ProfileLayout(
            name=name,
            profile_root=profile_root,
            workspace=workspace,
            deps_dir=profile_root / ".deps",
            run_dir=profile_root / ".sieve" / "runs",
            session_file=profile_root / ".sieve" / "session.json",
            prompt_file=profile_root / "CODEX_PROMPT.txt",
            bootstrap_log=profile_root / "bootstrap.log",
        )
    return layouts


def run_command(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )


def require_ok(proc: subprocess.CompletedProcess[str], step: str) -> None:
    if proc.returncode == 0:
        return
    raise RuntimeError(
        f"{step} failed with exit code {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def clone_repo(*, row: ManifestRow, workspace: Path) -> None:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    require_ok(
        run_command(["git", "clone", "--quiet", f"https://github.com/{row.repo}.git", str(workspace)], env=env),
        f"git clone {row.repo}",
    )
    require_ok(
        run_command(["git", "checkout", "--quiet", row.base_commit], cwd=workspace, env=env),
        f"git checkout {row.base_commit}",
    )


def build_child_pythonpath(layout: ProfileLayout) -> str:
    return os.pathsep.join([str(layout.workspace), str(layout.deps_dir)])


def _dependency_install_commands(layout: ProfileLayout, row: ManifestRow) -> list[list[str]]:
    commands: list[list[str]] = []
    target = str(layout.deps_dir)
    pip_prefix = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--target",
        target,
    ]
    repo_specific: dict[str, list[list[str]]] = {
        # This Astropy checkout predates recent setuptools changes and expects
        # legacy build helpers such as setuptools.dep_util during build_ext.
        "astropy/astropy": [
            [
                *pip_prefix,
                "setuptools<70",
                "setuptools_scm>=6.2",
                "wheel",
                "cython==0.29.22",
                "oldest-supported-numpy",
                "extension-helpers",
            ],
            [*pip_prefix, "hypothesis", "pyerfa", "pytest"],
        ],
    }
    if row.repo in repo_specific:
        return repo_specific[row.repo]

    # Prefer test/dev extras when available; workspace stays first on PYTHONPATH.
    commands.extend(
        [
            [*pip_prefix, ".[test]"],
            [*pip_prefix, ".[tests]"],
            [*pip_prefix, ".[dev]"],
            [*pip_prefix, "."],
        ]
    )

    req_candidates = [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_test.txt",
        "requirements-test.txt",
        "test-requirements.txt",
        "dev-requirements.txt",
    ]
    for name in req_candidates:
        path = layout.workspace / name
        if path.is_file():
            commands.append([*pip_prefix, "-r", str(path)])

    return commands


def _post_install_build_commands(layout: ProfileLayout, row: ManifestRow) -> list[list[str]]:
    env_pythonpath = build_child_pythonpath(layout)
    python = sys.executable
    repo_specific: dict[str, list[list[str]]] = {
        # Astropy imports from the workspace source tree, so compiled extension
        # modules must exist in-place rather than only in an installed wheel.
        "astropy/astropy": [
            ["env", f"PYTHONPATH={env_pythonpath}", python, "setup.py", "build_ext", "--inplace"],
        ],
    }
    return repo_specific.get(row.repo, [])


def bootstrap_workspace(layout: ProfileLayout, row: ManifestRow) -> None:
    layout.deps_dir.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    install_ok = False
    for cmd in _dependency_install_commands(layout, row):
        proc = run_command(cmd, cwd=layout.workspace)
        log_lines.append("$ " + " ".join(cmd))
        log_lines.append(proc.stdout)
        log_lines.append(proc.stderr)
        if proc.returncode == 0:
            install_ok = True
            break
    if install_ok:
        for cmd in _post_install_build_commands(layout, row):
            proc = run_command(cmd, cwd=layout.workspace)
            log_lines.append("$ " + " ".join(cmd))
            log_lines.append(proc.stdout)
            log_lines.append(proc.stderr)
    layout.bootstrap_log.write_text("\n".join(log_lines), encoding="utf-8")


def prepare_container_workspace(
    *,
    layout: ProfileLayout,
    row: ManifestRow,
    dataset: str,
    split: str,
) -> None:
    payload_path = layout.profile_root / "instance.json"
    payload_path.write_text(json.dumps(manifest_row_payload(row)), encoding="utf-8")
    cmd = [
        resolve_eval_python(),
        str(ROOT / "scripts" / "prepare_swe_lite_container_workspace.py"),
        "--instance-json",
        str(payload_path),
        "--workspace",
        str(layout.workspace),
        "--container-name",
        profile_container_name(layout),
        "--runtime-root",
        str(container_runtime_root(layout)),
        "--dataset",
        dataset,
        "--split",
        split,
    ]
    layout.bootstrap_log.parent.mkdir(parents=True, exist_ok=True)
    with layout.bootstrap_log.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            log.flush()
            sys.stderr.write(f"[prepare {row.instance_id} {layout.name}] {line}")
            sys.stderr.flush()
        returncode = proc.wait()
    if returncode != 0:
        raise RuntimeError(
            f"prepare container workspace {row.instance_id} {layout.name} failed with exit code {returncode}"
        )


def build_wrapped_command(
    layout: ProfileLayout,
    repo_root: Path,
    command_placeholder: str = "<YOUR_COMMAND>",
    environment_mode: str = LOCAL_HOST_CLONE,
) -> str:
    args = [
        "PYTHONPATH=" + os.pathsep.join([str(repo_root / "src"), str(repo_root)]),
        "python3",
        str(repo_root / "scripts" / "sieved_run.py"),
    ]
    if layout.name == "baseline":
        args.append("--no-sieve")
    args.extend(
        [
            "--save-raw",
            "--save-raw-dir",
            str(layout.run_dir),
            "--session-file",
            str(layout.session_file),
            "--",
        ]
    )
    if environment_mode == HARNESS_CONTAINER:
        args.extend(
            [
                "docker",
                "exec",
                "-i",
                "-w",
                "/testbed",
                profile_container_name(layout),
                "bash",
                "-lc",
                command_placeholder,
            ]
        )
    else:
        args.extend(
            [
                "env",
                f"PYTHONPATH={build_child_pythonpath(layout)}",
                "bash",
                "-lc",
                command_placeholder,
            ]
        )
    return " ".join(args)


def write_agent_prompt(
    *,
    layout: ProfileLayout,
    repo_root: Path,
    row: ManifestRow,
    environment_mode: str = LOCAL_HOST_CLONE,
) -> Path:
    wrapped = build_wrapped_command(layout, repo_root, environment_mode=environment_mode)
    noisy_rule = (
        "For noisy shell commands such as pytest, python -m pytest, pip install, mypy, ruff, eslint, or tsc, "
        "always use the wrapped command below so context is captured consistently."
    )
    if environment_mode == HARNESS_CONTAINER:
        environment_note = """Important environment note:
- This workspace is mounted into a container built from the official SWE-bench Lite instance image.
- Commands run through the wrapped command execute inside that container at `/testbed`.
- Official resolved scoring still happens later in the SWE-bench Docker harness, but local verification here uses the same instance environment model."""
        dependency_note = "The wrapped command runs inside the prepared SWE-bench container for this profile."
    else:
        environment_note = """Important environment note:
- This workspace is a local host-clone approximation of a SWE-bench Lite instance, not the official harness container.
- Official resolved scoring will happen later in the SWE-bench Docker harness.
- If local verification fails due to missing imports, build errors, or Python/runtime mismatch, report that as a local environment limitation rather than as evidence the patch is wrong."""
        dependency_note = f"The wrapped command already injects the prepared dependency layer from `{layout.deps_dir}`."
    text = f"""You are in the current working directory of a SWE-bench Lite repair experiment.

{environment_note}

Issue: {row.instance_id}
Repository: {row.repo}
Commit: {row.base_commit}

Problem statement:
{row.problem_statement}

Hard constraints:
- Only inspect and modify files inside the current working directory.
- Make the smallest correct code change.
- Do not change unrelated tests or project metadata.
- If you need to run noisy tooling, do not run it directly.
- {noisy_rule}

Wrapped command template:
{wrapped}

Replace <YOUR_COMMAND> with the command you want to run inside the repo checkout.
{dependency_note}

When done, report:
- changed files
- whether your final verification passed
- a short diff summary
"""
    layout.prompt_file.write_text(text, encoding="utf-8")
    return layout.prompt_file


def load_run_meta(run_dir: Path) -> dict[str, int]:
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


def write_instructions(
    *,
    instance_root: Path,
    repo_root: Path,
    row: ManifestRow,
    layouts: dict[str, ProfileLayout],
    environment_mode: str = LOCAL_HOST_CLONE,
) -> Path:
    baseline = layouts["baseline"]
    sieve = layouts["sieve"]
    if environment_mode == HARNESS_CONTAINER:
        mode_note = "This setup mounts each profile workspace into a container built from the official SWE-bench instance image."
    else:
        mode_note = "This setup is a local host-clone approximation for paired baseline/sieve trials."
    text = f"""# Codex SWE-bench Lite Experiment

Instance: `{row.instance_id}`

{mode_note}
Official SWE-bench Lite resolved scoring still happens later in the harness Docker environment.

Baseline workspace: `{baseline.workspace}`
Sieve workspace: `{sieve.workspace}`

Use a fresh agent session per profile. The only intended difference is the wrapped command mode:

- Baseline: `{build_wrapped_command(baseline, repo_root, environment_mode=environment_mode)}`
- Sieve: `{build_wrapped_command(sieve, repo_root, environment_mode=environment_mode)}`
"""
    path = instance_root / "README.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_summary(
    *,
    instance_root: Path,
    row: ManifestRow,
    layouts: dict[str, ProfileLayout],
    environment_mode: str = LOCAL_HOST_CLONE,
) -> Path:
    baseline = load_run_meta(layouts["baseline"].run_dir)
    sieve = load_run_meta(layouts["sieve"].run_dir)
    payload: dict[str, Any] = {
        "instance_id": row.instance_id,
        "repo": row.repo,
        "base_commit": row.base_commit,
        "environment_mode": environment_mode,
        "profiles": {
            "baseline": {
                "workspace": str(layouts["baseline"].workspace),
                "prompt_file": str(layouts["baseline"].prompt_file),
                "deps_dir": str(layouts["baseline"].deps_dir),
                "bootstrap_log": str(layouts["baseline"].bootstrap_log),
                "container_name": profile_container_name(layouts["baseline"])
                if environment_mode == HARNESS_CONTAINER
                else None,
                "context": baseline,
            },
            "sieve": {
                "workspace": str(layouts["sieve"].workspace),
                "prompt_file": str(layouts["sieve"].prompt_file),
                "deps_dir": str(layouts["sieve"].deps_dir),
                "bootstrap_log": str(layouts["sieve"].bootstrap_log),
                "container_name": profile_container_name(layouts["sieve"])
                if environment_mode == HARNESS_CONTAINER
                else None,
                "context": sieve,
            },
        },
        "comparison": {
            "agent_char_delta": baseline["agent_chars"] - sieve["agent_chars"],
            "raw_chars": baseline["raw_chars"],
        },
    }
    out = instance_root / "summary.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def prepare_instance(
    *,
    row: ManifestRow,
    work_root: Path,
    repo_root: Path,
    force: bool,
    environment_mode: str = LOCAL_HOST_CLONE,
    dataset: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
) -> dict[str, ProfileLayout]:
    instance_root = experiment_root(work_root, row.instance_id)
    if instance_root.exists():
        if not force:
            raise RuntimeError(f"instance already exists: {instance_root}")
        shutil.rmtree(instance_root)
    layouts = build_layouts(instance_root)
    for layout in layouts.values():
        layout.workspace.parent.mkdir(parents=True, exist_ok=True)
        if environment_mode == HARNESS_CONTAINER:
            prepare_container_workspace(layout=layout, row=row, dataset=dataset, split=split)
        else:
            clone_repo(row=row, workspace=layout.workspace)
            bootstrap_workspace(layout, row)
        write_agent_prompt(
            layout=layout,
            repo_root=repo_root,
            row=row,
            environment_mode=environment_mode,
        )
    write_instructions(
        instance_root=instance_root,
        repo_root=repo_root,
        row=row,
        layouts=layouts,
        environment_mode=environment_mode,
    )
    return layouts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--problem-statement", required=True)
    parser.add_argument("--work-root", type=Path, default=ROOT / "artifacts" / "codex-swe-bench-lite")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--environment-mode",
        choices=(LOCAL_HOST_CLONE, HARNESS_CONTAINER),
        default=LOCAL_HOST_CLONE,
    )
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--split", default="test")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    row = ManifestRow(
        instance_id=args.instance_id,
        repo=args.repo,
        base_commit=args.base_commit,
        problem_statement=args.problem_statement,
    )
    layouts = prepare_instance(
        row=row,
        work_root=args.work_root.resolve(),
        repo_root=args.repo_root.resolve(),
        force=args.force,
        environment_mode=args.environment_mode,
        dataset=args.dataset,
        split=args.split,
    )
    summary_path = write_summary(
        instance_root=experiment_root(args.work_root.resolve(), args.instance_id),
        row=row,
        layouts=layouts,
        environment_mode=args.environment_mode,
    )
    print(f"prepared experiment: {experiment_root(args.work_root.resolve(), args.instance_id)}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
