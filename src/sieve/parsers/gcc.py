from __future__ import annotations

import re

from sieve.config import CompressConfig
from sieve.core import DiagnosticItem, RawExecution, Severity, Status, StructuredOutput


DIAG_RE = re.compile(
    r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<level>fatal error|error|warning|note):\s+(?P<msg>.*)$"
)
COMPILER_TOKEN = re.compile(r"\b(gcc|g\+\+|clang|clang\+\+|cc|c\+\+|cpp)\b")


class GccParser:
    """Parses gcc/clang diagnostic output. Drops source-context lines and
    'In file included from' chains; groups notes under the prior error."""

    tool_type = "gcc"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        if COMPILER_TOKEN.search(execution.command.lower()):
            return True
        output = execution.combined_output
        # Need to see at least one diagnostic header line that's clearly
        # gcc-shaped (file:line:col: level: ...) — distinguishing from mypy
        # (which has no column for default mode and has [code] suffixes).
        for line in output.splitlines():
            match = DIAG_RE.match(line)
            if match and match.group("level") in {"error", "fatal error"}:
                # mypy lines almost always end with " [some-code]"; gcc don't
                if not re.search(r"\s+\[[\w-]+\]\s*$", line):
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
            col = int(match.group("col"))
            message = match.group("msg").strip()

            if level == "note":
                if items:
                    items[-1].related.append(f"{file_path}:{line_no}: {message}")
                continue

            severity = Severity.WARNING if level == "warning" else Severity.ERROR
            items.append(
                DiagnosticItem(
                    severity=severity,
                    file=file_path,
                    line=line_no,
                    column=col,
                    code=None,
                    message=message,
                    tool="gcc",
                )
            )

        summary = self._build_summary(items)
        status = Status.SUCCESS if execution.exit_code == 0 and not items else Status.FAILURE
        return StructuredOutput(
            tool_type=self.tool_type,
            status=status,
            summary=summary,
            items=items,
            raw_line_count=len(lines),
            compressed_line_count=1 + len(items),
            raw_content=raw,
        )

    def _build_summary(self, items: list[DiagnosticItem]) -> str:
        # Note: the delta engine prefixes the tool_type, so the summary itself
        # should not. Returning a bare phrase prevents "GCC: GCC: ..." in
        # rendered output.
        errors = sum(1 for i in items if i.severity == Severity.ERROR)
        warnings = sum(1 for i in items if i.severity == Severity.WARNING)
        if errors == 0 and warnings == 0:
            return "clean"
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        return ", ".join(parts)
