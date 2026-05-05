from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_run_tokens import load_bundle, render_report


class AnalyzeRunTokensTests(unittest.TestCase):
    def test_load_bundle_reads_sibling_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            meta = tmp / "demo.meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "mode": "sieve",
                        "raw_chars": 7,
                        "agent_chars": 3,
                        "saved_chars": 4,
                    }
                ),
                encoding="utf-8",
            )
            (tmp / "demo.stdout.txt").write_text("hello\n", encoding="utf-8")
            (tmp / "demo.stderr.txt").write_text("x", encoding="utf-8")
            (tmp / "demo.agent.txt").write_text("hey", encoding="utf-8")

            bundle = load_bundle(meta)

        self.assertEqual(bundle.mode, "sieve")
        self.assertEqual(bundle.raw_text, "hello\nx")
        self.assertEqual(bundle.agent_text, "hey")

    def test_render_report_includes_char_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for stem, mode, agent in (("a", "baseline", 10), ("b", "sieve", 4)):
                (tmp / f"{stem}.meta.json").write_text(
                    json.dumps(
                        {
                            "mode": mode,
                            "raw_chars": 12,
                            "agent_chars": agent,
                            "saved_chars": 12 - agent,
                        }
                    ),
                    encoding="utf-8",
                )
                (tmp / f"{stem}.stdout.txt").write_text("abcdef", encoding="utf-8")
                (tmp / f"{stem}.stderr.txt").write_text("ghijkl", encoding="utf-8")
                (tmp / f"{stem}.agent.txt").write_text("x" * agent, encoding="utf-8")

            report = render_report(
                baseline=load_bundle(tmp / "a.meta.json"),
                sieve=load_bundle(tmp / "b.meta.json"),
                encoding_name=None,
            )

        self.assertIn("agent char delta", report)
        self.assertIn("6", report)


if __name__ == "__main__":
    unittest.main()
