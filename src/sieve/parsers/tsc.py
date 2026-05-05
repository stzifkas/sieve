from __future__ import annotations

import re

from sieve.config import CompressConfig
from sieve.core import DiagnosticItem, RawExecution, Severity, Status, StructuredOutput


# Pretty format: src/foo.ts:12:5 - error TS2345: message
PRETTY_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)\s+-\s+"
    r"(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<msg>.*)$"
)
# Legacy format: src/foo.ts(12,5): error TS2345: message
LEGACY_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s+"
    r"(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<msg>.*)$"
)
SUMMARY_RE = re.compile(r"^Found\s+(\d+)\s+errors?\s+in\s+(\d+)\s+files?\.")
TS_ERROR_TOKEN = re.compile(r"\berror\s+TS\d+:")


class TscParser:
    tool_type = "tsc"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        command = execution.command.lower()
        if "tsc" in command or "typescript" in command:
            return True
        return bool(TS_ERROR_TOKEN.search(execution.combined_output))

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        items: list[DiagnosticItem] = []

        for line in lines:
            match = PRETTY_RE.match(line) or LEGACY_RE.match(line)
            if not match:
                continue
            severity = (
                Severity.WARNING
                if match.group("level") == "warning"
                else Severity.ERROR
            )
            items.append(
                DiagnosticItem(
                    severity=severity,
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    code=match.group("code"),
                    message=match.group("msg").strip(),
                    tool="tsc",
                )
            )

        summary = self._build_summary(lines, items)
        return StructuredOutput(
            tool_type=self.tool_type,
            status=Status.SUCCESS if execution.exit_code == 0 and not items else Status.FAILURE,
            summary=summary,
            items=items,
            raw_line_count=len(lines),
            compressed_line_count=1 + len(items),
            raw_content=raw,
        )

    def _build_summary(self, lines: list[str], items: list[DiagnosticItem]) -> str:
        for line in reversed(lines):
            stripped = line.strip()
            if SUMMARY_RE.match(stripped):
                return stripped
        errors = sum(1 for i in items if i.severity == Severity.ERROR)
        if errors == 0:
            return "TSC: no errors"
        return f"TSC: {errors} error{'s' if errors != 1 else ''}"
