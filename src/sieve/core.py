from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TypeAlias


class Status(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    TIMEOUT = "timeout"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(slots=True)
class ErrorSignature:
    error_type: str
    file: str
    message_hash: str
    first_seen_turn: int = 0

    def matches(self, other: "ErrorSignature") -> bool:
        return (
            self.error_type == other.error_type
            and self.file == other.file
            and self.message_hash == other.message_hash
        )


@dataclass(slots=True)
class RawExecution:
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    timestamp: float = 0.0

    @property
    def combined_output(self) -> str:
        if self.stdout and self.stderr:
            return f"{self.stdout.rstrip()}\n{self.stderr.lstrip()}".rstrip()
        return (self.stdout or self.stderr).rstrip()


@dataclass(slots=True)
class TestResult:
    id: str
    status: Literal["passed", "failed", "error", "skipped"]
    file: str
    line: int | None
    assertion: str | None = None
    actual: str | None = None
    expected: str | None = None
    duration_ms: float | None = None
    message: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def short_error(self) -> str:
        if self.actual is not None and self.expected is not None:
            return f"expected {self.expected}, got {self.actual}"
        if self.message:
            return self.message
        if self.assertion:
            return self.assertion
        return self.status

    @property
    def compressed_repr(self) -> str:
        location = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.id} ({location}) - {self.short_error}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "file": self.file,
            "line": self.line,
            "assertion": self.assertion,
            "actual": self.actual,
            "expected": self.expected,
            "duration_ms": self.duration_ms,
            "message": self.message,
        }


@dataclass(slots=True)
class RuntimeErrorItem:
    error_type: str
    message: str
    file: str
    line: int
    function: str | None
    call_chain: list[str]
    variable_hint: str | None = None
    severity: Severity = Severity.ERROR

    @property
    def signature(self) -> ErrorSignature:
        normalized = " ".join(self.message.split())
        return ErrorSignature(
            error_type=self.error_type,
            file=self.file,
            message_hash=hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
        )

    @property
    def compressed_repr(self) -> str:
        func = f" ({self.function})" if self.function else ""
        return f"{self.error_type} in {self.file}:{self.line}{func} - {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "call_chain": self.call_chain,
            "variable_hint": self.variable_hint,
            "severity": self.severity.value,
        }


@dataclass(slots=True)
class TextOutputItem:
    text: str
    severity: Severity = Severity.INFO

    @property
    def compressed_repr(self) -> str:
        return self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "severity": self.severity.value,
        }


@dataclass(slots=True)
class DiagnosticItem:
    """Compile-time / lint diagnostic from tools like gcc, tsc, mypy, eslint."""

    severity: Severity
    file: str
    line: int | None
    column: int | None
    code: str | None
    message: str
    tool: str
    related: list[str] = field(default_factory=list)

    @property
    def signature(self) -> ErrorSignature:
        normalized = " ".join(self.message.split())
        return ErrorSignature(
            error_type=self.code or self.tool,
            file=self.file,
            message_hash=hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
        )

    @property
    def compressed_repr(self) -> str:
        if self.line is not None and self.column is not None:
            location = f"{self.file}:{self.line}:{self.column}"
        elif self.line is not None:
            location = f"{self.file}:{self.line}"
        else:
            location = self.file
        code = f" [{self.code}]" if self.code else ""
        sev = self.severity.value
        return f"{sev} {location}{code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "code": self.code,
            "message": self.message,
            "tool": self.tool,
            "related": self.related,
        }


OutputItem: TypeAlias = TestResult | RuntimeErrorItem | DiagnosticItem | TextOutputItem


@dataclass(slots=True)
class StructuredOutput:
    tool_type: str
    status: Status
    summary: str
    items: list[OutputItem] = field(default_factory=list)
    raw_line_count: int = 0
    compressed_line_count: int = 0
    raw_content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def test_results(self) -> list[TestResult]:
        return [item for item in self.items if isinstance(item, TestResult)]


@dataclass(slots=True)
class CompressedOutput:
    tool_type: str
    status: Status
    summary: str
    content: str
    items: list[OutputItem] = field(default_factory=list)
    compression_ratio: float = 0.0
    raw_chars: int = 0
    compressed_chars: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool_type,
            "status": self.status.value,
            "summary": self.summary,
            "content": self.content,
            "items": [item.to_dict() for item in self.items],
            "compression": f"{self.compression_ratio:.0%}",
        }
