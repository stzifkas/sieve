from __future__ import annotations

import re

from sieve.config import CompressConfig
from sieve.core import DiagnosticItem, RawExecution, Severity, Status, StructuredOutput


DIAG_RE = re.compile(
    r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+)(?::(?P<col>\d+))?: "
    r"(?P<level>error|warning|note): (?P<msg>.*?)"
    r"(?:\s+\[(?P<code>[\w-]+)\])?$"
)
SUMMARY_RE = re.compile(
    r"^Found\s+(\d+)\s+errors?\s+in\s+(\d+)\s+files?", re.IGNORECASE
)
SUCCESS_RE = re.compile(r"^Success:\s+no issues found", re.IGNORECASE)


class MypyParser:
    tool_type = "mypy"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        command = execution.command.lower()
        if "mypy" in command:
            return True
        output = execution.combined_output
        if SUMMARY_RE.search(output) and ": error:" in output:
            return True
        if SUCCESS_RE.search(output):
            return True
        return False

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        items: list[DiagnosticItem] = []

        for line in lines:
            match = DIAG_RE.match(line)
            if not match:
                continue
            level = match.group("level")
            file_path = match.group("file")
            line_no = int(match.group("line"))
            col = int(match.group("col")) if match.group("col") else None
            message = match.group("msg").strip()
            code = match.group("code")

            if level == "note":
                if items:
                    note = f"{file_path}:{line_no}: {message}"
                    items[-1].related.append(note)
                continue

            severity = Severity.WARNING if level == "warning" else Severity.ERROR
            items.append(
                DiagnosticItem(
                    severity=severity,
                    file=file_path,
                    line=line_no,
                    column=col,
                    code=code,
                    message=message,
                    tool="mypy",
                )
            )

        summary = self._build_summary(lines, items)
        status = self._infer_status(execution, items)

        return StructuredOutput(
            tool_type=self.tool_type,
            status=status,
            summary=summary,
            items=items,
            raw_line_count=len(lines),
            compressed_line_count=1 + len(items),
            raw_content=raw,
        )

    def _build_summary(self, lines: list[str], items: list[DiagnosticItem]) -> str:
        for line in reversed(lines):
            stripped = line.strip()
            if SUMMARY_RE.match(stripped) or SUCCESS_RE.match(stripped):
                return stripped
        errors = sum(1 for i in items if i.severity == Severity.ERROR)
        warnings = sum(1 for i in items if i.severity == Severity.WARNING)
        if not errors and not warnings:
            return "MYPY: clean"
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        return "MYPY: " + ", ".join(parts)

    def _infer_status(
        self, execution: RawExecution, items: list[DiagnosticItem]
    ) -> Status:
        if execution.exit_code == 0:
            return Status.SUCCESS
        if any(i.severity == Severity.ERROR for i in items):
            return Status.FAILURE
        return Status.FAILURE
