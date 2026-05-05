from __future__ import annotations

from dataclasses import dataclass, field

from sieve.core import ErrorSignature, TestResult
from sieve.stats import TokenStats


@dataclass(slots=True)
class FileSnapshot:
    hash: str
    turn_read: int


@dataclass(slots=True)
class TestDelta:
    new_failures: list[TestResult] = field(default_factory=list)
    changed_failures: list[tuple[TestResult, TestResult]] = field(default_factory=list)
    resolved_failures: list[tuple[TestResult, TestResult]] = field(default_factory=list)
    unchanged_failures: list[TestResult] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.new_failures or self.changed_failures or self.resolved_failures)


class SessionState:
    def __init__(self, *, track_stats: bool = True):
        self.turn: int = 0
        self.test_results: dict[str, TestResult] = {}
        self.seen_errors: list[ErrorSignature] = []
        self.read_files: dict[str, FileSnapshot] = {}
        self.build_status: object | None = None
        self.token_stats = TokenStats()
        self.track_stats = track_stats

    def advance_turn(self) -> None:
        self.turn += 1

    def get_test_delta(self, current_failures: list[TestResult]) -> TestDelta:
        delta = TestDelta()
        current_map = {test.id: test for test in current_failures}
        previous_failures = {
            test_id: result
            for test_id, result in self.test_results.items()
            if result.status in {"failed", "error"}
        }

        for test_id, previous in previous_failures.items():
            current = current_map.get(test_id)
            if current is None:
                passed = TestResult(
                    id=previous.id,
                    status="passed",
                    file=previous.file,
                    line=previous.line,
                    duration_ms=previous.duration_ms,
                )
                delta.resolved_failures.append((previous, passed))
            elif (
                previous.status != current.status
                or previous.short_error != current.short_error
            ):
                delta.changed_failures.append((previous, current))
            else:
                delta.unchanged_failures.append(current)

        for test_id, current in current_map.items():
            if test_id not in previous_failures:
                delta.new_failures.append(current)

        for previous, passed in delta.resolved_failures:
            self.test_results[previous.id] = passed
        for test in current_failures:
            self.test_results[test.id] = test

        return delta

    def is_error_seen(self, error: ErrorSignature) -> tuple[bool, int | None]:
        for seen in self.seen_errors:
            if seen.matches(error):
                return True, seen.first_seen_turn
        error.first_seen_turn = self.turn
        self.seen_errors.append(error)
        return False, None

    def is_file_unchanged(self, path: str, content_hash: str) -> tuple[bool, int | None]:
        snapshot = self.read_files.get(path)
        if snapshot and snapshot.hash == content_hash:
            return True, snapshot.turn_read
        self.read_files[path] = FileSnapshot(hash=content_hash, turn_read=self.turn)
        return False, None

    def record_compression(
        self,
        *,
        raw_chars: int,
        compressed_chars: int,
        delta_hit: bool = False,
        dedup_hit: bool = False,
    ) -> None:
        if not self.track_stats:
            return
        self.token_stats.total_raw_chars += raw_chars
        self.token_stats.total_compressed_chars += compressed_chars
        self.token_stats.turns_processed += 1
        if delta_hit:
            self.token_stats.delta_hits += 1
        if dedup_hit:
            self.token_stats.dedup_hits += 1
