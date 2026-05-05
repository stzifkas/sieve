"""Minimal MCP upstream server used by the proxy smoke test.

Exposes a single 'bash' tool that, regardless of input, returns a canned
pytest fixture as its TextContent. Lets us drive the proxy without depending
on a real bash MCP server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "pytest"
    / "two_failures.txt"
)


async def main() -> int:
    server: Server = Server("test-upstream")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="bash",
                description="Run a shell command and return its output.",
                inputSchema={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        del name, arguments
        return [TextContent(type="text", text=FIXTURE.read_text())]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
