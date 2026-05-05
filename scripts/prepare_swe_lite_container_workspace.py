#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

import docker
from docker.errors import NotFound

from swebench.harness.constants import DOCKER_USER, DOCKER_WORKDIR, KEY_INSTANCE_ID, LATEST
from swebench.harness.docker_build import build_instance_images
from swebench.harness.docker_utils import cleanup_container
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.utils import load_swebench_dataset


def _merge_missing_instance_fields(row: dict, *, dataset: str, split: str) -> dict:
    required = {"version", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"}
    if required.issubset(row):
        return row

    dataset_rows = load_swebench_dataset(dataset, split, instance_ids=[row[KEY_INSTANCE_ID]])
    if not dataset_rows:
        raise RuntimeError(f"instance not found in dataset: {row[KEY_INSTANCE_ID]}")
    merged = dict(dataset_rows[0])
    merged.update({k: v for k, v in row.items() if v not in (None, "")})
    return merged


def _remove_container_if_exists(client: docker.DockerClient, name: str) -> None:
    try:
        cleanup_container(client, client.containers.get(name), logger="quiet")
    except NotFound:
        return


def _copy_tree_from_container(container: docker.models.containers.Container, src: str, dest: Path) -> None:
    stream, _ = container.get_archive(src)
    payload = io.BytesIO(b"".join(stream))
    extract_root = dest.parent / f".{dest.name}.extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=payload) as tar:
        tar.extractall(path=extract_root)
    extracted_children = list(extract_root.iterdir())
    if len(extracted_children) != 1:
        raise RuntimeError(f"unexpected archive layout while copying {src}: {extracted_children}")
    if dest.exists():
        shutil.rmtree(dest)
    extracted_children[0].rename(dest)
    shutil.rmtree(extract_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-json", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--split", default="test")
    parser.add_argument("--force-rebuild-images", action="store_true")
    args = parser.parse_args()

    args.runtime_root.mkdir(parents=True, exist_ok=True)
    os.chdir(args.runtime_root)
    os.environ.setdefault("HF_HOME", str(args.runtime_root / "hf_home"))
    os.environ.setdefault("HF_DATASETS_CACHE", str(args.runtime_root / "hf_datasets"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(args.runtime_root / "hf_home" / "hub"))
    os.environ.setdefault("XDG_CACHE_HOME", str(args.runtime_root / "xdg_cache"))

    print(f"runtime_root={args.runtime_root}", file=sys.stderr, flush=True)
    print(f"workspace={args.workspace}", file=sys.stderr, flush=True)
    print(f"container_name={args.container_name}", file=sys.stderr, flush=True)
    row = json.loads(args.instance_json.read_text(encoding="utf-8"))
    print(f"hydrate_instance={row[KEY_INSTANCE_ID]}", file=sys.stderr, flush=True)
    row = _merge_missing_instance_fields(row, dataset=args.dataset, split=args.split)

    print("connect_docker", file=sys.stderr, flush=True)
    client = docker.from_env()
    test_spec = make_test_spec(row)
    print(f"build_instance_image={test_spec.instance_image_key}", file=sys.stderr, flush=True)
    build_instance_images(
        client,
        [row],
        force_rebuild=args.force_rebuild_images,
        max_workers=1,
        tag=LATEST,
        env_image_tag=LATEST,
    )

    args.workspace.parent.mkdir(parents=True, exist_ok=True)
    _remove_container_if_exists(client, args.container_name)

    seed_name = f"{args.container_name}-seed"
    _remove_container_if_exists(client, seed_name)
    seed_container = None
    mounted_container = None
    run_args = test_spec.docker_specs.get("run_args", {})
    cap_add = run_args.get("cap_add", [])
    try:
        print("create_seed_container", file=sys.stderr, flush=True)
        seed_container = client.containers.create(
            image=test_spec.instance_image_key,
            name=seed_name,
            user=DOCKER_USER,
            detach=True,
            command="tail -f /dev/null",
            working_dir=DOCKER_WORKDIR,
            platform=test_spec.platform,
            cap_add=cap_add,
        )
        seed_container.start()
        print("copy_testbed_to_workspace", file=sys.stderr, flush=True)
        _copy_tree_from_container(seed_container, DOCKER_WORKDIR, args.workspace)
    finally:
        cleanup_container(client, seed_container, logger="quiet")

    print("create_mounted_container", file=sys.stderr, flush=True)
    mounted_container = client.containers.create(
        image=test_spec.instance_image_key,
        name=args.container_name,
        user=DOCKER_USER,
        detach=True,
        command="tail -f /dev/null",
        working_dir=DOCKER_WORKDIR,
        platform=test_spec.platform,
        cap_add=cap_add,
        volumes={str(args.workspace): {"bind": DOCKER_WORKDIR, "mode": "rw"}},
    )
    mounted_container.start()
    mounted_container.exec_run(f"git config --global --add safe.directory {DOCKER_WORKDIR}")
    print("container_ready", file=sys.stderr, flush=True)

    print(
        json.dumps(
            {
                "instance_id": row[KEY_INSTANCE_ID],
                "workspace": str(args.workspace),
                "container_name": args.container_name,
                "instance_image_key": test_spec.instance_image_key,
                "platform": test_spec.platform,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
