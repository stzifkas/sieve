"""Compressing MCP proxy.

The proxy speaks MCP on stdio in both directions:

    agent ⇄  this proxy  ⇄  upstream MCP server

`tools/list` is forwarded verbatim, so the agent sees the same tool surface as
the upstream. `tools/call` is forwarded, then every TextContent block in the
result is run through a shared CompressSession before being returned. Other
content types (images, embedded resources) pass through unchanged.

A single CompressSession is held for the proxy's lifetime, so cross-tool delta
compression works (e.g. running pytest twice in a row, or hitting the same
runtime error from different tool invocations, both benefit from session
state).

Usage from a CLI:

    python -m sieve.integrations.mcp -- <upstream-cmd> [args...]

Configure the MCP client (Claude Desktop, etc.) to launch this command instead
of the upstream server directly. No application code changes needed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolResult,
        EmbeddedResource,
        ImageContent,
        TextContent,
        Tool,
    )
except ImportError as exc:  # pragma: no cover - optional dep guard
    raise ImportError(
        "sieve.integrations.mcp requires the optional 'mcp' dependency. "
        "Install with: pip install 'sieve[mcp]'"
    ) from exc

from sieve import CompressConfig, CompressSession


ContentBlock = TextContent | ImageContent | EmbeddedResource


class CompressMCPProxy:
    """Wraps an upstream MCP server, compressing TextContent in tool results."""

    def __init__(
        self,
        upstream_command: list[str],
        *,
        config: CompressConfig | None = None,
        session: CompressSession | None = None,
        server_name: str = "sieve-proxy",
    ) -> None:
        if not upstream_command:
            raise ValueError("upstream_command must not be empty")
        self.upstream_command = list(upstream_command)
        self.session = session or CompressSession(config=config)
        self.server_name = server_name

    async def serve(self) -> None:
        params = StdioServerParameters(
            command=self.upstream_command[0],
            args=self.upstream_command[1:],
        )
        async with stdio_client(params) as (up_read, up_write):
            async with ClientSession(up_read, up_write) as upstream:
                await upstream.initialize()
                server = self._build_server(upstream)
                async with stdio_server() as (read, write):
                    await server.run(
                        read, write, server.create_initialization_options()
                    )

    def _build_server(self, upstream: ClientSession) -> Server:
        server: Server = Server(self.server_name)

        @server.list_tools()
        async def _list_tools() -> list[Tool]:
            result = await upstream.list_tools()
            return list(result.tools)

        @server.call_tool()
        async def _call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[ContentBlock]:
            result = await upstream.call_tool(name, arguments or {})
            return self._compress_result(result, name, arguments or {})

        return server

    def _compress_result(
        self,
        result: CallToolResult,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> list[ContentBlock]:
        command = self._derive_command(tool_name, arguments)
        exit_code = 1 if result.isError else 0
        compressed: list[ContentBlock] = []
        for block in result.content:
            if isinstance(block, TextContent):
                comp = self.session.compress(
                    command=command,
                    stdout=block.text,
                    exit_code=exit_code,
                )
                compressed.append(TextContent(type="text", text=comp.text))
            else:
                compressed.append(block)
        return compressed

    @staticmethod
    def _derive_command(tool_name: str, arguments: dict[str, Any]) -> str:
        """Surface the raw shell command to Sieve's parser router when the
        upstream tool exposes one. Bash-like servers commonly use 'command' or
        'cmd' as the argument name; we check those before falling back to the
        tool name itself."""
        for key in ("command", "cmd", "shellCommand"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value
        return tool_name


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="python -m sieve.integrations.mcp",
        description=(
            "Compressing MCP proxy. Forwards tools/list and tools/call to an "
            "upstream MCP server, compressing TextContent in results."
        ),
    )
    parser.add_argument(
        "--name",
        default="sieve-proxy",
        help="Server name announced to the MCP client (default: sieve-proxy)",
    )
    parser.add_argument(
        "upstream",
        nargs=argparse.REMAINDER,
        help="Upstream command and args (preceded by --)",
    )
    args = parser.parse_args(argv)
    upstream = list(args.upstream)
    if upstream and upstream[0] == "--":
        upstream = upstream[1:]
    return args, upstream


def main(argv: list[str] | None = None) -> int:
    args, upstream = _parse_args(argv if argv is not None else sys.argv[1:])
    if not upstream:
        print(
            "error: missing upstream command. Usage: "
            "python -m sieve.integrations.mcp -- <command> [args...]",
            file=sys.stderr,
        )
        return 2
    proxy = CompressMCPProxy(upstream, server_name=args.name)
    asyncio.run(proxy.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
