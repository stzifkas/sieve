from __future__ import annotations

from collections import Counter

from sieve.config import CompressConfig
from sieve.core import RawExecution, Status, StructuredOutput


class GenericParser:
    tool_type = "generic"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        return True

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        compressed_lines = self._compress_lines(lines)
        summary = self._build_summary(lines, compressed_lines, execution.exit_code)

        return StructuredOutput(
            tool_type=self.tool_type,
            status=self._infer_status(execution),
            summary=summary,
            items=[],
            raw_line_count=len(lines),
            compressed_line_count=len(compressed_lines),
            raw_content=raw,
            metadata={
                "display_lines": compressed_lines,
                "repeated_lines": {
                    line: count for line, count in Counter(lines).items() if count >= self.config.generic_dedup_threshold
                },
            },
        )

    def _compress_lines(self, lines: list[str]) -> list[str]:
        if len(lines) <= self.config.max_raw_lines:
            return lines

        deduped = self._dedup(lines)
        if len(deduped) <= self.config.max_raw_lines:
            return deduped

        head = deduped[: self.config.generic_head_lines]
        tail = deduped[-self.config.generic_tail_lines :]
        omitted = max(len(deduped) - len(head) - len(tail), 0)
        return head + [f"[... {omitted} lines omitted ...]"] + tail

    def _dedup(self, lines: list[str]) -> list[str]:
        if not lines:
            return []

        output: list[str] = []
        current = lines[0]
        run_length = 1

        def flush(line: str, count: int) -> None:
            output.append(line)
            if count >= self.config.generic_dedup_threshold:
                output.append(f"[previous line repeated {count - 1} more times]")
            else:
                output.extend([line] * (count - 1))

        for line in lines[1:]:
            if line == current:
                run_length += 1
                continue
            flush(current, run_length)
            current = line
            run_length = 1

        flush(current, run_length)
        return output

    def _build_summary(
        self,
        raw_lines: list[str],
        compressed_lines: list[str],
        exit_code: int,
    ) -> str:
        if not raw_lines:
            return "Output: empty"
        if len(raw_lines) == len(compressed_lines):
            if exit_code == 0:
                return f"Output: {len(raw_lines)} lines"
            return f"Command failed with {len(raw_lines)} lines of output"
        return f"Output: {len(raw_lines)} lines -> {len(compressed_lines)} lines"

    def _infer_status(self, execution: RawExecution) -> Status:
        if execution.exit_code == 0:
            return Status.SUCCESS
        return Status.FAILURE
