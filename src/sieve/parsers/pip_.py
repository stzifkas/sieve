from __future__ import annotations

import re

from sieve.config import CompressConfig
from sieve.core import RawExecution, Severity, Status, StructuredOutput, TextOutputItem


SUCCESS_RE = re.compile(r"^Successfully installed\s+(.+)$")
PIP_COMMAND_RE = re.compile(r"\b(?:pip3?|python3?\s+-m\s+pip)\s+install\b")
# Pip emits authoritative failure messages with uppercase ERROR:. Subprocess
# stderr ("error: subprocess-exited-with-error") is too generic to be useful
# as the failure summary, so we only anchor on the uppercase form.
ERROR_LINE_RE = re.compile(r"^\s*ERROR:\s+(.+)$")


class PipParser:
    """Compresses pip install output. Success runs collapse to a one-line
    package count; failures keep just the error block."""

    tool_type = "pip"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        if PIP_COMMAND_RE.search(execution.command):
            return True
        output = execution.combined_output
        return "Successfully installed" in output or (
            "Collecting " in output and "Downloading " in output
        )

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        installed = self._extract_installed(lines)
        error_block = self._extract_error_block(lines)

        if error_block and execution.exit_code != 0:
            summary = f"PIP FAIL: {error_block.splitlines()[0][:200]}"
            items = [TextOutputItem(text=error_block, severity=Severity.ERROR)]
            status = Status.FAILURE
        elif installed:
            count = len(installed)
            summary = f"PIP: installed {count} package{'s' if count != 1 else ''}"
            items = []
            status = Status.SUCCESS
        else:
            summary = (
                "PIP: nothing to do"
                if execution.exit_code == 0
                else "PIP FAIL: unknown error"
            )
            items = []
            status = Status.SUCCESS if execution.exit_code == 0 else Status.FAILURE

        return StructuredOutput(
            tool_type=self.tool_type,
            status=status,
            summary=summary,
            items=items,
            raw_line_count=len(lines),
            compressed_line_count=1 if not items else 1 + len(error_block.splitlines() if error_block else []),
            raw_content=raw,
            metadata={"installed_packages": installed} if installed else {},
        )

    def _extract_installed(self, lines: list[str]) -> list[str]:
        for line in reversed(lines):
            match = SUCCESS_RE.match(line.strip())
            if match:
                return [pkg for pkg in match.group(1).split() if pkg]
        return []

    def _extract_error_block(self, lines: list[str]) -> str | None:
        # First ERROR: line and the few lines following (until blank or new section)
        for index, line in enumerate(lines):
            if ERROR_LINE_RE.match(line):
                block: list[str] = [line.rstrip()]
                for follow in lines[index + 1 : index + 6]:
                    if not follow.strip():
                        break
                    if ERROR_LINE_RE.match(follow):
                        break
                    block.append(follow.rstrip())
                return "\n".join(block)
        return None
