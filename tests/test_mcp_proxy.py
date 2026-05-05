from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

try:
    from mcp.types import (
        CallToolResult,
        EmbeddedResource,
        ImageContent,
        TextContent,
        TextResourceContents,
    )

    from sieve.integrations.mcp import CompressMCPProxy

    HAS_MCP = True
except ImportError:  # pragma: no cover
    HAS_MCP = False


FIXTURES = Path(__file__).parent / "fixtures"


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class DeriveCommandTests(unittest.TestCase):
    def test_returns_command_when_present(self) -> None:
        cmd = CompressMCPProxy._derive_command("bash", {"command": "pytest tests/"})
        self.assertEqual(cmd, "pytest tests/")

    def test_falls_back_to_alternative_keys(self) -> None:
        for key in ("cmd", "shellCommand"):
            with self.subTest(key=key):
                cmd = CompressMCPProxy._derive_command("bash", {key: "ls -la"})
                self.assertEqual(cmd, "ls -la")

    def test_falls_back_to_tool_name(self) -> None:
        cmd = CompressMCPProxy._derive_command("read_file", {"path": "/tmp/x"})
        self.assertEqual(cmd, "read_file")

    def test_ignores_non_string_values(self) -> None:
        cmd = CompressMCPProxy._derive_command("bash", {"command": 42})
        self.assertEqual(cmd, "bash")


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class CompressResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = CompressMCPProxy(["echo", "noop"])  # upstream not actually launched

    def _make_result(self, text: str, *, is_error: bool = False) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            isError=is_error,
        )

    def test_compresses_text_content_through_pytest_parser(self) -> None:
        raw = (FIXTURES / "pytest" / "two_failures.txt").read_text()
        result = self._make_result(raw, is_error=True)
        out = self.proxy._compress_result(result, "bash", {"command": "pytest tests/"})

        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], TextContent)
        text = out[0].text
        # Massively shorter
        self.assertLess(len(text), len(raw) // 3)
        # Key facts survive
        self.assertIn("test_user_update", text)
        self.assertIn("test_user_delete", text)
        self.assertIn("403", text)
        # Sieve framing visible
        self.assertIn("PYTEST", text)

    def test_passes_through_non_text_content_unchanged(self) -> None:
        image = ImageContent(type="image", data="aGVsbG8=", mimeType="image/png")
        result = CallToolResult(content=[image], isError=False)
        out = self.proxy._compress_result(result, "screenshot", {})

        self.assertEqual(len(out), 1)
        self.assertIs(out[0], image)

    def test_mixed_content_compresses_only_text(self) -> None:
        raw = (FIXTURES / "pytest" / "two_failures.txt").read_text()
        text_block = TextContent(type="text", text=raw)
        embedded = EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri="file:///tmp/log.txt", mimeType="text/plain", text="log"
            ),
        )
        result = CallToolResult(
            content=[text_block, embedded],
            isError=True,
        )
        out = self.proxy._compress_result(result, "bash", {"command": "pytest"})

        self.assertEqual(len(out), 2)
        self.assertIsInstance(out[0], TextContent)
        self.assertLess(len(out[0].text), len(raw))
        self.assertIs(out[1], embedded)

    def test_session_state_persists_across_calls_for_delta(self) -> None:
        raw = (FIXTURES / "pytest" / "two_failures.txt").read_text()
        first = self.proxy._compress_result(
            self._make_result(raw, is_error=True),
            "bash",
            {"command": "pytest"},
        )
        second = self.proxy._compress_result(
            self._make_result(raw, is_error=True),
            "bash",
            {"command": "pytest"},
        )
        # Second call should benefit from delta compression — typically
        # shorter than the first because unchanged failures collapse.
        self.assertIsInstance(first[0], TextContent)
        self.assertIsInstance(second[0], TextContent)
        self.assertIn("PYTEST DELTA", second[0].text)


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class ConstructionTests(unittest.TestCase):
    def test_rejects_empty_upstream_command(self) -> None:
        with self.assertRaises(ValueError):
            CompressMCPProxy([])


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class EndToEndProxyTests(unittest.IsolatedAsyncioTestCase):
    """Spawns the proxy as a subprocess wrapping a tiny upstream server, then
    connects an MCP client to the proxy and verifies that the round-trip
    returns compressed output."""

    async def test_proxy_compresses_pytest_output_round_trip(self) -> None:
        import sys
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        upstream_script = (
            Path(__file__).parent / "mcp_helpers" / "upstream_server.py"
        )
        raw_size = (
            FIXTURES / "pytest" / "two_failures.txt"
        ).read_text().__len__()

        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "sieve.integrations.mcp",
                "--",
                sys.executable,
                str(upstream_script),
            ],
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                tools = await client.list_tools()
                self.assertTrue(any(t.name == "bash" for t in tools.tools))

                result = await client.call_tool(
                    "bash", {"command": "pytest tests/"}
                )
                self.assertEqual(len(result.content), 1)
                block = result.content[0]
                self.assertEqual(block.type, "text")

                # Compressed: PYTEST framing present, way smaller than raw
                self.assertIn("PYTEST", block.text)
                self.assertIn("test_user_update", block.text)
                self.assertLess(len(block.text), raw_size // 3)


if __name__ == "__main__":
    unittest.main()
