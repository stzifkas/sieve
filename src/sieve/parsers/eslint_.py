from __future__ import annotations

import re

from sieve.config import CompressConfig
from sieve.core import DiagnosticItem, RawExecution, Severity, Status, StructuredOutput


DIAG_RE = re.compile(
    r"^\s+(?P<line>\d+):(?P<col>\d+)\s+"
    r"(?P<level>error|warning)\s+"
    r"(?P<msg>.+?)\s+(?P<rule>\S+)$"
)
SUMMARY_RE = re.compile(
    r"^[✖x]\s+\d+\s+problems?\s+\(", re.IGNORECASE
)
PROBLEM_COUNT_RE = re.compile(
    r"(\d+)\s+errors?,\s*(\d+)\s+warnings?", re.IGNORECASE
)


class EslintParser:
    tool_type = "eslint"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        command = execution.command.lower()
        if "eslint" in command:
            return True
        output = execution.combined_output
        return bool(SUMMARY_RE.search(output)) and bool(DIAG_RE.search(output))

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        items: list[DiagnosticItem] = []
        current_file: str | None = None

        for line in lines:
            if SUMMARY_RE.match(line.strip()):
                break
            if not line:
                continue
            if not line[0].isspace():
                stripped = line.strip()
                # File path heading
                if stripped and not stripped.startswith(("error", "warning", "✖")):
                    current_file = stripped
                continue
            match = DIAG_RE.match(line)
            if not match or current_file is None:
                continue
            severity = (
                Severity.WARNING if match.group("level") == "warning" else Severity.ERROR
            )
            items.append(
                DiagnosticItem(
                    severity=severity,
                    file=current_file,
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    code=match.group("rule"),
                    message=match.group("msg").strip(),
                    tool="eslint",
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
        warnings = sum(1 for i in items if i.severity == Severity.WARNING)
        if not errors and not warnings:
            return "ESLINT: clean"
        return f"ESLINT: {errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}"
