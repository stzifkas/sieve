from __future__ import annotations

from pathlib import Path

from sieve.config import CompressConfig
from sieve.core import (
    CompressedOutput,
    DiagnosticItem,
    RuntimeErrorItem,
    Status,
    StructuredOutput,
    TestResult,
)
from sieve.session import SessionState


DIAGNOSTIC_TOOLS = frozenset({"gcc", "tsc", "mypy", "eslint"})


class DeltaEngine:
    def __init__(self, config: CompressConfig):
        self.config = config

    def compress(self, parsed: StructuredOutput, session: SessionState) -> CompressedOutput:
        session.advance_turn()

        if parsed.tool_type == "pytest":
            compressed = self._compress_tests(parsed, session)
        elif parsed.tool_type == "python_traceback":
            compressed = self._compress_runtime(parsed, session)
        elif parsed.tool_type in DIAGNOSTIC_TOOLS:
            compressed = self._compress_diagnostics(parsed, session)
        elif parsed.tool_type == "pip":
            compressed = self._compress_pip(parsed, session)
        else:
            compressed = self._compress_generic(parsed)

        session.record_compression(
            raw_chars=len(parsed.raw_content),
            compressed_chars=len(compressed.content),
            delta_hit=bool(compressed.metadata.get("delta_hit")),
            dedup_hit=bool(compressed.metadata.get("dedup_hit")),
        )
        return compressed

    def _compress_tests(self, parsed: StructuredOutput, session: SessionState) -> CompressedOutput:
        failures = parsed.test_results
        delta = session.get_test_delta(failures)

        if session.turn == 1 or not self.config.delta_mode:
            lines = [f"PYTEST: {parsed.summary}"]
            lines.extend(self._render_failures(failures))
            pattern_hint = parsed.metadata.get("pattern_hint")
            if pattern_hint:
                lines.append(f"Pattern: {pattern_hint}")
            content = "\n".join(lines)
            return self._build_output(parsed, content, delta_hit=False)

        if not delta.has_changes:
            lines = [f"PYTEST DELTA: unchanged - {parsed.summary}"]
            if delta.unchanged_failures:
                for failure in delta.unchanged_failures:
                    lines.append(f"STILL FAIL {failure.id} - {failure.short_error}")
            content = "\n".join(lines)
            return self._build_output(parsed, content, delta_hit=True)

        lines = [f"PYTEST DELTA (turn {session.turn})"]
        for previous, _ in delta.resolved_failures:
            lines.append(f"PASS {previous.id} now passes")
        for _, current in delta.changed_failures:
            lines.append(
                f"{self._result_prefix(current)} {current.id}"
                f"{self._location_suffix(current)} changed - {current.short_error}"
            )
        for current in delta.new_failures:
            lines.append(
                f"{self._result_prefix(current)} {current.id}"
                f"{self._location_suffix(current)} - {current.short_error}"
            )
        for failure in delta.unchanged_failures:
            lines.append(
                f"STILL {self._result_prefix(failure)} {failure.id}"
                f"{self._location_suffix(failure)} - {failure.short_error}"
            )
        lines.append(f"Result: {parsed.summary}")
        content = "\n".join(lines)
        return self._build_output(parsed, content, delta_hit=True)

    def _compress_runtime(self, parsed: StructuredOutput, session: SessionState) -> CompressedOutput:
        item = parsed.items[0] if parsed.items else None
        if not isinstance(item, RuntimeErrorItem):
            return self._compress_generic(parsed)

        seen, turn = session.is_error_seen(item.signature)
        location = ""
        if item.file != "<unknown>" and item.line:
            location = f" in {item.file}:{item.line}"
        lines = [f"RUNTIME ERROR: {item.error_type}{location}"]
        lines.append(f"  {item.message}")
        related = parsed.metadata.get("related_exceptions")
        if isinstance(related, list) and related:
            lines.append(f"  Context: {related[0]}")
        source_context = parsed.metadata.get("source_context")
        if isinstance(source_context, list):
            for source_line in source_context[:2]:
                lines.append(f"  Source: {source_line}")
        if item.call_chain:
            lines.append(f"  Call chain: {' -> '.join(item.call_chain)}")

        if seen and self.config.delta_mode and turn is not None:
            lines.insert(0, f"RUNTIME DELTA: same error as turn {turn}")

        content = "\n".join(lines)
        return self._build_output(parsed, content, delta_hit=seen, dedup_hit=seen)

    def _compress_diagnostics(
        self, parsed: StructuredOutput, session: SessionState
    ) -> CompressedOutput:
        diagnostics = [item for item in parsed.items if isinstance(item, DiagnosticItem)]
        header = f"{parsed.tool_type.upper()}: {parsed.summary}"
        lines: list[str] = [header]
        any_seen = False

        for item in diagnostics:
            seen, turn = session.is_error_seen(item.signature)
            any_seen = any_seen or seen
            if seen and self.config.delta_mode and turn is not None:
                lines.append(
                    f"  [same as turn {turn}] {item.file}:{item.line} - "
                    f"{item.code or item.severity.value}"
                )
            else:
                lines.append(f"  {item.compressed_repr}")
                for note in item.related[:1]:
                    lines.append(f"    note: {note}")

        if not diagnostics:
            # Clean run; surface just the summary line.
            return self._build_output(parsed, header, delta_hit=False)

        content = "\n".join(lines)
        return self._build_output(
            parsed, content, delta_hit=any_seen, dedup_hit=any_seen
        )

    def _compress_pip(
        self, parsed: StructuredOutput, session: SessionState
    ) -> CompressedOutput:
        # Success cases collapse to a single line; failure cases keep the
        # error block. No cross-turn dedup yet.
        del session  # unused, kept for parity / future use
        if parsed.status == Status.SUCCESS:
            return self._build_output(parsed, parsed.summary, delta_hit=False)
        # The summary already contains the first error-block line, so just
        # surface remaining lines of the block (skip the duplicate).
        lines = [parsed.summary]
        for item in parsed.items:
            extra = item.compressed_repr.splitlines()[1:]
            lines.extend(extra)
        return self._build_output(parsed, "\n".join(lines), delta_hit=False)

    def _compress_generic(self, parsed: StructuredOutput) -> CompressedOutput:
        display_lines = parsed.metadata.get("display_lines")
        if isinstance(display_lines, list):
            content = "\n".join(display_lines)
        else:
            content = parsed.raw_content

        if parsed.status == Status.SUCCESS and parsed.summary:
            content = f"{parsed.summary}\n{content}".strip()
        return self._build_output(parsed, content, delta_hit=False)

    def _render_failures(self, failures: list[TestResult]) -> list[str]:
        lines: list[str] = []
        for failure in failures:
            location = f"{Path(failure.file).name}:{failure.line}" if failure.line else Path(failure.file).name
            lines.append(f"{self._result_prefix(failure)} {failure.id} ({location})")
            if failure.actual is not None and failure.expected is not None:
                lines.append(f"  expected {failure.expected}, got {failure.actual}")
            else:
                lines.append(f"  {failure.short_error}")
        return lines

    def _result_prefix(self, result: TestResult) -> str:
        if result.status == "error":
            return "ERROR"
        return "FAIL"

    def _location_suffix(self, result: TestResult) -> str:
        """Filename:line tag, or empty when no line is known. The test id
        already carries the file path, so we only emit the line."""
        if result.line is None:
            return ""
        return f" (line {result.line})"

    def _build_output(
        self,
        parsed: StructuredOutput,
        content: str,
        *,
        delta_hit: bool,
        dedup_hit: bool = False,
    ) -> CompressedOutput:
        raw_chars = len(parsed.raw_content)
        # Compressor contract: never produce content larger than the raw input.
        # When framing overhead exceeds savings (typically on already-terse
        # inputs), pass the raw content through unchanged.
        if raw_chars and len(content) > raw_chars:
            content = parsed.raw_content
            delta_hit = False
            dedup_hit = False
        compressed_chars = len(content)
        if raw_chars == 0:
            ratio = 0.0
        else:
            ratio = 1 - compressed_chars / raw_chars
        ratio = min(ratio, self.config.max_compression_ratio)

        return CompressedOutput(
            tool_type=parsed.tool_type,
            status=parsed.status,
            summary=parsed.summary,
            content=content,
            items=parsed.items,
            compression_ratio=max(ratio, 0.0),
            raw_chars=raw_chars,
            compressed_chars=compressed_chars,
            metadata={"delta_hit": delta_hit, "dedup_hit": dedup_hit},
        )
