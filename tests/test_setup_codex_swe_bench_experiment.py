from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.setup_codex_swe_bench_experiment import (
    HARNESS_CONTAINER,
    ManifestRow,
    LOCAL_HOST_CLONE,
    _dependency_install_commands,
    _post_install_build_commands,
    build_child_pythonpath,
    build_layouts,
    build_wrapped_command,
    experiment_root,
    write_agent_prompt,
    write_instructions,
    write_summary,
)


class SetupCodexSweBenchExperimentTests(unittest.TestCase):
    def test_build_layouts_uses_profile_scoped_paths(self) -> None:
        root = experiment_root(Path("/tmp/experiments"), "astropy__astropy-12907")
        layouts = build_layouts(root)

        self.assertEqual(
            layouts["baseline"].workspace,
            root / "baseline" / "workspace",
        )
        self.assertEqual(
            layouts["sieve"].workspace,
            root / "sieve" / "workspace",
        )
        self.assertEqual(
            layouts["baseline"].session_file,
            root / "baseline" / ".sieve" / "session.json",
        )
        self.assertEqual(
            layouts["baseline"].prompt_file,
            root / "baseline" / "CODEX_PROMPT.txt",
        )
        self.assertEqual(
            layouts["baseline"].deps_dir,
            root / "baseline" / ".deps",
        )

    def test_write_summary_computes_agent_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            instance_root = Path(tmpdir)
            layouts = build_layouts(instance_root)
            for name, chars in (("baseline", (100, 80, 20)), ("sieve", (100, 30, 70))):
                layouts[name].run_dir.mkdir(parents=True, exist_ok=True)
                (layouts[name].run_dir / f"{name}.meta.json").write_text(
                    json.dumps(
                        {
                            "raw_chars": chars[0],
                            "agent_chars": chars[1],
                            "saved_chars": chars[2],
                        }
                    ),
                    encoding="utf-8",
                )

            summary_path = write_summary(
                instance_root=instance_root,
                row=ManifestRow(
                    instance_id="astropy__astropy-12907",
                    repo="astropy/astropy",
                    base_commit="abc",
                    problem_statement="bug",
                ),
                layouts=layouts,
            )

            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["comparison"]["agent_char_delta"], 50)
            self.assertEqual(payload["profiles"]["sieve"]["context"]["agent_chars"], 30)
            self.assertIn("deps_dir", payload["profiles"]["baseline"])
            self.assertIn("bootstrap_log", payload["profiles"]["baseline"])

    def test_write_instructions_mentions_both_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            instance_root = Path(tmpdir)
            layouts = build_layouts(instance_root)
            readme = write_instructions(
                instance_root=instance_root,
                repo_root=Path("/repo"),
                row=ManifestRow(
                    instance_id="astropy__astropy-12907",
                    repo="astropy/astropy",
                    base_commit="abc",
                    problem_statement="bug",
                ),
                layouts=layouts,
            )

            text = readme.read_text(encoding="utf-8")
            self.assertIn("Baseline workspace", text)
            self.assertIn("Sieve workspace", text)
            self.assertIn("scripts/sieved_run.py --no-sieve", text)

    def test_wrapped_command_injects_workspace_and_deps_pythonpath(self) -> None:
        layouts = build_layouts(Path("/tmp/exp"))
        cmd = build_wrapped_command(layouts["baseline"], Path("/repo"))

        self.assertIn("env PYTHONPATH=", cmd)
        self.assertIn(str(layouts["baseline"].workspace), build_child_pythonpath(layouts["baseline"]))
        self.assertIn(str(layouts["baseline"].deps_dir), build_child_pythonpath(layouts["baseline"]))

    def test_harness_container_wrapped_command_execs_inside_container(self) -> None:
        layouts = build_layouts(Path("/tmp/exp"))
        cmd = build_wrapped_command(
            layouts["sieve"],
            Path("/repo"),
            environment_mode=HARNESS_CONTAINER,
        )

        self.assertIn("docker exec -i -w /testbed", cmd)
        self.assertIn("sweb.agent.", cmd)
        self.assertNotIn("env PYTHONPATH=", cmd)

    def test_astropy_gets_inplace_build_step(self) -> None:
        layout = build_layouts(Path("/tmp/exp"))["baseline"]
        commands = _post_install_build_commands(
            layout,
            ManifestRow(
                instance_id="astropy__astropy-12907",
                repo="astropy/astropy",
                base_commit="abc",
                problem_statement="bug",
            ),
        )

        self.assertTrue(commands)
        self.assertIn("setup.py", commands[0])
        self.assertIn("build_ext", commands[0])
        self.assertIn("--inplace", commands[0])

    def test_astropy_bootstrap_uses_repo_specific_build_toolchain(self) -> None:
        layout = build_layouts(Path("/tmp/exp"))["baseline"]
        commands = _dependency_install_commands(
            layout,
            ManifestRow(
                instance_id="astropy__astropy-12907",
                repo="astropy/astropy",
                base_commit="abc",
                problem_statement="bug",
            ),
        )

        self.assertEqual(len(commands), 2)
        self.assertIn("setuptools<70", commands[0])
        self.assertIn("extension-helpers", commands[0])
        self.assertIn("hypothesis", commands[1])
        self.assertNotIn(".[test]", commands[0])

    def test_agent_prompt_calls_out_local_host_clone_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            layout = build_layouts(Path(tmpdir))["baseline"]
            layout.profile_root.mkdir(parents=True, exist_ok=True)
            prompt_path = write_agent_prompt(
                layout=layout,
                repo_root=Path("/repo"),
                row=ManifestRow(
                    instance_id="astropy__astropy-12907",
                    repo="astropy/astropy",
                    base_commit="abc",
                    problem_statement="bug",
                ),
                environment_mode=LOCAL_HOST_CLONE,
            )

            text = prompt_path.read_text(encoding="utf-8")
            self.assertIn("local host-clone approximation", text)
            self.assertIn("official harness container", text)

    def test_agent_prompt_calls_out_harness_container_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            layout = build_layouts(Path(tmpdir))["baseline"]
            layout.profile_root.mkdir(parents=True, exist_ok=True)
            prompt_path = write_agent_prompt(
                layout=layout,
                repo_root=Path("/repo"),
                row=ManifestRow(
                    instance_id="astropy__astropy-12907",
                    repo="astropy/astropy",
                    base_commit="abc",
                    problem_statement="bug",
                ),
                environment_mode=HARNESS_CONTAINER,
            )

            text = prompt_path.read_text(encoding="utf-8")
            self.assertIn("official SWE-bench Lite instance image", text)
            self.assertIn("execute inside that container", text)


if __name__ == "__main__":
    unittest.main()
