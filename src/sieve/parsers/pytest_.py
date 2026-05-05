from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sieve.config import CompressConfig
from sieve.core import RawExecution, Status, StructuredOutput, TestResult


DETAIL_HEADER_RE = re.compile(r"^_+\s+(.+?)\s+_+$")
FILE_LINE_RE = re.compile(r"^(.+):(\d+)(?::(?:\s+(.*))?)?$")
SECTION_RE = re.compile(r"^=+\s+(FAILURES|ERRORS)\s+=+$")
SUMMARY_ENTRY_RE = re.compile(
    r"^(FAILED|ERROR|PASSED|SKIPPED|XFAIL(?:ED)?|XPASS(?:ED)?)\s+(.+?)(?:\s+-\s+(.*))?$"
)
COUNT_RE = re.compile(r"(\d+)\s+((?:x)?passed|(?:x)?failed|skipped|warnings?|errors?)", re.IGNORECASE)
COLLECTED_RE = re.compile(r"collected\s+(\d+)\s+items?(?:\s*/\s*(\d+)\s+errors?)?", re.IGNORECASE)


class PytestParser:
    tool_type = "pytest"

    def __init__(self, config: CompressConfig):
        self.config = config

    def supports(self, execution: RawExecution) -> bool:
        command = execution.command.lower()
        output = execution.combined_output
        if "pytest" in command:
            return True
        return (
            "test session starts" in output
            or "short test summary info" in output.lower()
            or bool(re.search(r"\bcollected\s+\d+\s+items?\b", output))
            or bool(re.search(r"^FAILED\s+.+::.+", output, re.MULTILINE))
            or bool(re.search(r"^ERROR\s+.+(?:\.py|::.+)", output, re.MULTILINE))
        )

    def parse(self, execution: RawExecution) -> StructuredOutput:
        raw = execution.combined_output
        lines = raw.splitlines()
        counts = self._parse_counts(lines)
        summary_entries = self._parse_short_summary(lines)
        detail_blocks = self._parse_detail_blocks(lines)

        failures: list[TestResult] = []
        for entry in summary_entries:
            status = entry["status"]
            nodeid = entry["nodeid"]
            message = entry["message"]
            details = self._match_details(nodeid, detail_blocks)
            file_path = self._infer_file_path(nodeid)
            line = None
            assertion = None
            actual = None
            expected = None
            detail_message = message

            if details:
                file_path = details["file"] or file_path
                line = details["line"]
                assertion = details["assertion"]
                actual = details["actual"]
                expected = details["expected"]
                detail_message = details["message"] or detail_message

            failures.append(
                TestResult(
                    id=nodeid,
                    status=status,
                    file=file_path,
                    line=line,
                    assertion=assertion,
                    actual=actual,
                    expected=expected,
                    message=detail_message,
                )
            )

        summary = self._build_summary(counts, failures)
        metadata: dict[str, object] = {"counts": counts}
        pattern_hint = self._pattern_hint(failures)
        if pattern_hint and self.config.include_pattern_hints:
            metadata["pattern_hint"] = pattern_hint

        compressed_lines = 1 + (2 * len(failures))
        if pattern_hint and self.config.include_pattern_hints:
            compressed_lines += 1

        return StructuredOutput(
            tool_type=self.tool_type,
            status=self._infer_status(execution.exit_code, failures),
            summary=summary,
            items=failures,
            raw_line_count=len(lines),
            compressed_line_count=compressed_lines,
            raw_content=raw,
            metadata=metadata,
        )

    def _parse_counts(self, lines: list[str]) -> dict[str, int]:
        for line in reversed(lines):
            if not any(token in line.lower() for token in ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "warning")):
                continue
            counts = {}
            for value, label in COUNT_RE.findall(line):
                counts[self._normalize_count_label(label)] = int(value)
            if counts:
                collected = self._parse_collected_count(lines)
                if collected is not None:
                    counts["collected"] = collected
                return counts
        collected = self._parse_collected_count(lines)
        if collected is not None:
            counts = {"collected": collected}
            for line in lines:
                match = COLLECTED_RE.search(line)
                if match and match.group(2):
                    counts["error"] = int(match.group(2))
                    break
            if counts:
                return counts
        return {}

    def _parse_short_summary(self, lines: list[str]) -> list[dict[str, Any]]:
        in_summary = False
        results: list[dict[str, Any]] = []

        for line in lines:
            lower = line.lower().strip()
            if "short test summary info" in lower:
                in_summary = True
                continue
            if not in_summary:
                continue

            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("="):
                break

            entry = self._parse_summary_entry(stripped)
            if entry is None:
                continue
            results.append(entry)

        if results:
            return results

        fallback_results: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for line in lines:
            entry = self._parse_summary_entry(line.strip())
            if entry is None:
                continue
            key = (entry["status"], entry["nodeid"])
            if key in seen:
                continue
            seen.add(key)
            fallback_results.append(entry)
        return fallback_results

    def _parse_detail_blocks(self, lines: list[str]) -> list[tuple[str, list[str]]]:
        details: list[tuple[str, list[str]]] = []
        active_section = False
        current_name: str | None = None
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if "short test summary info" in stripped.lower():
                break

            if SECTION_RE.match(stripped):
                active_section = True
                if current_name:
                    details.append((current_name, current_lines[:]))
                    current_name = None
                    current_lines = []
                continue

            if not active_section:
                continue

            match = DETAIL_HEADER_RE.match(stripped)
            if match:
                header = match.group(1).strip()
                if self._is_auxiliary_header(header):
                    if current_name is not None:
                        current_lines.append(line)
                    continue
                if current_name:
                    details.append((current_name, current_lines[:]))
                current_name = header
                current_lines = [line]
                continue

            if current_name is not None:
                current_lines.append(line)

        if current_name:
            details.append((current_name, current_lines))

        return details

    def _match_details(
        self,
        nodeid: str,
        blocks: list[tuple[str, list[str]]],
    ) -> dict[str, object] | None:
        parts = nodeid.split("::")
        candidates = [
            nodeid,
            "::".join(parts[-2:]) if len(parts) > 2 else None,
            parts[-1],
            self._infer_file_path(nodeid),
        ]
        normalized_candidates = {
            candidate.replace(" ", "").lower()
            for candidate in candidates
            if candidate
        }

        for name, block_lines in blocks:
            normalized_name = name.replace(" ", "").lower()
            if any(
                normalized_name.endswith(candidate)
                or candidate.endswith(normalized_name)
                or candidate in normalized_name
                for candidate in normalized_candidates
            ):
                return self._extract_failure_details(block_lines, self._infer_file_path(nodeid))

        return None

    def _extract_failure_details(
        self,
        lines: list[str],
        default_file: str | None,
    ) -> dict[str, object]:
        file_path: str | None = default_file
        line_no: int | None = None
        assertion: str | None = None
        actual: str | None = None
        expected: str | None = None
        message: str | None = None
        locations: list[tuple[str, int, str | None]] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(">"):
                assertion = stripped[1:].strip()
            if stripped.startswith("E"):
                normalized_error = re.sub(r"^E\s*", "", stripped).strip()
                parsed_actual, parsed_expected = self._extract_assertion_values(normalized_error)
                if parsed_actual is not None and parsed_expected is not None:
                    actual = parsed_actual
                    expected = parsed_expected
                if normalized_error and (message is None or message.startswith("in ")):
                    message = normalized_error

            match = FILE_LINE_RE.match(stripped)
            if match:
                locations.append((match.group(1), int(match.group(2)), match.group(3)))
                if message is None and match.group(3):
                    message = match.group(3).strip()

        selected_location = self._select_location(locations, default_file)
        if selected_location is not None:
            file_path, line_no, trailing_message = selected_location
            if message is None and trailing_message:
                message = trailing_message.strip()

        return {
            "file": file_path,
            "line": line_no,
            "assertion": assertion,
            "actual": actual,
            "expected": expected,
            "message": message,
        }

    def _extract_assertion_values(self, line: str) -> tuple[str | None, str | None]:
        match = re.search(r"assert\s+(.+?)\s*==\s*(.+)$", line)
        if not match:
            return None, None
        return match.group(1).strip(), match.group(2).strip()

    def _build_summary(
        self,
        counts: dict[str, int],
        failures: list[TestResult],
    ) -> str:
        fallback_failed = sum(1 for failure in failures if failure.status == "failed")
        fallback_errors = sum(1 for failure in failures if failure.status == "error")

        failed = counts.get("failed", fallback_failed)
        passed = counts.get("passed", 0)
        errors = counts.get("error", fallback_errors)
        skipped = counts.get("skipped", 0)
        xfailed = counts.get("xfailed", 0)
        xpassed = counts.get("xpassed", 0)
        warnings = counts.get("warning", 0)
        total = counts.get("collected", failed + passed + errors + skipped + xfailed + xpassed)

        summary_parts: list[str] = []
        if failed:
            summary_parts.append(self._count_phrase(failed, "failed", "failed"))
        if errors:
            summary_parts.append(self._count_phrase(errors, "error", "errors"))
        if passed:
            summary_parts.append(self._count_phrase(passed, "passed", "passed"))
        if skipped:
            summary_parts.append(self._count_phrase(skipped, "skipped", "skipped"))
        if xfailed:
            summary_parts.append(self._count_phrase(xfailed, "xfailed", "xfailed"))
        if xpassed:
            summary_parts.append(self._count_phrase(xpassed, "xpassed", "xpassed"))
        if warnings:
            summary_parts.append(self._count_phrase(warnings, "warning", "warnings"))
        if not summary_parts:
            fallback_total = len(failures)
            summary_parts.append(self._count_phrase(fallback_total, "failed", "failed"))
            if total == 0:
                total = fallback_total

        total_suffix = f" ({total} total)" if total else ""
        return ", ".join(summary_parts) + total_suffix

    def _pattern_hint(self, failures: list[TestResult]) -> str | None:
        actuals = {failure.actual for failure in failures if failure.actual is not None}
        files = {Path(failure.file).name for failure in failures if failure.file}
        if len(failures) > 1 and len(actuals) == 1:
            actual = next(iter(actuals))
            file_hint = f" in {next(iter(files))}" if len(files) == 1 else ""
            return f"All failures return {actual}{file_hint}"
        return None

    def _parse_summary_entry(self, line: str) -> dict[str, Any] | None:
        match = SUMMARY_ENTRY_RE.match(line)
        if not match:
            return None

        status_token, raw_target, message = match.groups()
        if status_token not in {"FAILED", "ERROR"}:
            return None
        status = "error" if status_token == "ERROR" else "failed"
        target = raw_target.strip()
        normalized_message = message.strip() if message else None

        if status == "error":
            lowered = target.lower()
            for prefix in ("at setup of ", "at teardown of ", "collecting "):
                if lowered.startswith(prefix):
                    target = target[len(prefix) :].strip()
                    break

        return {
            "status": status,
            "nodeid": target,
            "message": normalized_message,
        }

    def _normalize_count_label(self, label: str) -> str:
        lowered = label.lower()
        if lowered == "errors":
            return "error"
        if lowered == "warnings":
            return "warning"
        return lowered

    def _infer_file_path(self, nodeid: str) -> str:
        if "::" in nodeid:
            return nodeid.split("::", 1)[0]
        return nodeid

    def _select_location(
        self,
        locations: list[tuple[str, int, str | None]],
        default_file: str | None,
    ) -> tuple[str, int, str | None] | None:
        if not locations:
            return None
        if default_file:
            normalized_default = default_file.replace("\\", "/")
            for location in reversed(locations):
                candidate = location[0].replace("\\", "/")
                if candidate.endswith(normalized_default):
                    return location
        return locations[-1]

    def _is_auxiliary_header(self, header: str) -> bool:
        lowered = header.lower()
        return lowered.startswith("captured ") or "warnings summary" in lowered

    def _infer_status(self, exit_code: int, failures: list[TestResult]) -> Status:
        if exit_code == 0:
            return Status.SUCCESS
        if failures and all(failure.status == "error" for failure in failures):
            return Status.ERROR
        return Status.FAILURE

    def _count_phrase(self, value: int, singular: str, plural: str) -> str:
        label = singular if value == 1 else plural
        return f"{value} {label}"

    def _parse_collected_count(self, lines: list[str]) -> int | None:
        for line in lines:
            match = COLLECTED_RE.search(line)
            if match:
                return int(match.group(1))
        return None
