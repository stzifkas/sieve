from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sieve.config import CompressConfig
from sieve.core import RawExecution, RuntimeErrorItem, Status, StructuredOutput


FRAME_RE = re.compile(r'^File "(.+?)", line (\d+)(?:, in (.+))?$')
ERROR_RE = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Group))(?::\s*(.*))?$"
)
TRACEBACK_HEADER_RE = re.compile(
    r"^(Traceback \(most recent call last\):|Exception Group Traceback \(most recent call last\):)$"
)


class PythonTracebackParser:
    tool_type = "python_traceback"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        output = execution.combined_output
        if (
            "Traceback (most recent call last):" in output
            or "Exception Group Traceback (most recent call last):" in output
        ):
            return True
        last_line = self._last_non_empty_line(output)
        return bool(last_line and ERROR_RE.match(last_line))

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        last_header = self._last_traceback_header_index(lines)
        exception_info = self._extract_exception_info(lines, last_header)

        error_type = exception_info["error_type"]
        message = exception_info["message"]
        frames = exception_info["frames"]
        related_exceptions = exception_info["related_exceptions"]

        primary_file = "<unknown>"
        primary_line = 0
        primary_func: str | None = None
        if frames:
            primary_file, primary_line, primary_func, _, _ = frames[-1]

        call_chain = [
            f"{Path(file_path).name}:{line_no}"
            for file_path, line_no, _, _, _ in frames[-3:]
        ]
        item = RuntimeErrorItem(
            error_type=error_type,
            message=message,
            file=primary_file,
            line=primary_line,
            function=primary_func,
            call_chain=call_chain,
        )

        func = f" ({primary_func})" if primary_func else ""
        if primary_file != "<unknown>" and primary_line:
            summary = f"{error_type} in {primary_file}:{primary_line}{func}"
        else:
            summary = f"{error_type}: {message}"

        return StructuredOutput(
            tool_type=self.tool_type,
            status=Status.ERROR if execution.exit_code != 0 else Status.SUCCESS,
            summary=summary,
            items=[item],
            raw_line_count=len(lines),
            compressed_line_count=min(len(lines), 4),
            raw_content=raw,
            metadata={
                "frame_count": len(frames),
                "related_exceptions": related_exceptions,
                "source_context": frames[-1][3] if frames and frames[-1][3] else [],
            },
        )

    def _extract_exception_info(
        self,
        lines: list[str],
        last_header: int | None,
    ) -> dict[str, Any]:
        if last_header is not None:
            frames = self._extract_frames(lines, start=last_header + 1)
            primary = self._first_exception_after(lines, start=last_header + 1)
            related = self._related_exceptions(lines, last_header + 1, primary_index=primary[2] if primary else None)
            if primary is not None:
                return {
                    "error_type": primary[0],
                    "message": primary[1],
                    "frames": frames,
                    "related_exceptions": related,
                }

        all_frames = self._extract_frames(lines, start=0)
        matches = self._all_exception_lines(lines)
        if matches:
            error_type, message, primary_index = matches[-1]
            related = [
                f"{kind}: {detail}" if detail else kind
                for kind, detail, _ in matches[:-1]
            ]
            filtered_frames = [frame for frame in all_frames if frame[4] <= primary_index]
            return {
                "error_type": error_type,
                "message": message,
                "frames": filtered_frames,
                "related_exceptions": related,
            }

        return {
            "error_type": "RuntimeError",
            "message": "unknown error",
            "frames": all_frames,
            "related_exceptions": [],
        }

    def _extract_frames(
        self,
        lines: list[str],
        *,
        start: int,
    ) -> list[tuple[str, int, str | None, list[str], int]]:
        frames: list[tuple[str, int, str | None, list[str], int]] = []
        for index in range(start, len(lines)):
            cleaned = self._strip_prefix(lines[index])
            match = FRAME_RE.match(cleaned)
            if not match:
                continue
            file_path, line_no, function = match.groups()
            context = self._frame_context(lines, index)
            frames.append(
                (
                    file_path,
                    int(line_no),
                    function.strip() if function else None,
                    context,
                    index,
                )
            )
        return frames

    def _frame_context(self, lines: list[str], frame_index: int) -> list[str]:
        context: list[str] = []
        for offset in (1, 2):
            next_index = frame_index + offset
            if next_index >= len(lines):
                break
            cleaned = self._strip_prefix(lines[next_index]).rstrip()
            if not cleaned or TRACEBACK_HEADER_RE.match(cleaned) or ERROR_RE.match(cleaned):
                break
            context.append(cleaned)
        return context

    def _first_exception_after(
        self,
        lines: list[str],
        *,
        start: int,
    ) -> tuple[str, str, int] | None:
        for index in range(start, len(lines)):
            cleaned = self._strip_prefix(lines[index]).strip()
            match = ERROR_RE.match(cleaned)
            if match:
                return (
                    match.group(1),
                    (match.group(2) or "").strip() or "raised",
                    index,
                )
        return None

    def _all_exception_lines(self, lines: list[str]) -> list[tuple[str, str, int]]:
        matches: list[tuple[str, str, int]] = []
        for index, line in enumerate(lines):
            cleaned = self._strip_prefix(line).strip()
            match = ERROR_RE.match(cleaned)
            if not match:
                continue
            matches.append(
                (
                    match.group(1),
                    (match.group(2) or "").strip() or "raised",
                    index,
                )
            )
        return matches

    def _related_exceptions(
        self,
        lines: list[str],
        start: int,
        *,
        primary_index: int | None,
    ) -> list[str]:
        related: list[str] = []
        for error_type, message, index in self._all_exception_lines(lines):
            if primary_index is not None and index == primary_index:
                continue
            if primary_index is not None and index < start - 1:
                related.append(f"{error_type}: {message}" if message else error_type)
            elif primary_index is not None and index > primary_index:
                related.append(f"{error_type}: {message}" if message else error_type)
        return related

    def _last_traceback_header_index(self, lines: list[str]) -> int | None:
        for index in range(len(lines) - 1, -1, -1):
            cleaned = self._strip_prefix(lines[index]).strip()
            if TRACEBACK_HEADER_RE.match(cleaned):
                return index
        return None

    def _strip_prefix(self, line: str) -> str:
        return re.sub(r"^[\s|+\->]*", "", line)

    def _last_non_empty_line(self, text: str) -> str | None:
        for line in reversed(text.splitlines()):
            cleaned = self._strip_prefix(line).strip()
            if cleaned:
                return cleaned
        return None
