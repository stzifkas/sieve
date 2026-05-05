from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OutputFormat(str, Enum):
    PLAIN = "plain"
    STRUCTURED = "structured"
    XML = "xml"
    MINIMAL = "minimal"


@dataclass(slots=True)
class CompressConfig:
    format: OutputFormat = OutputFormat.PLAIN
    delta_mode: bool = True
    max_history_turns: int = 20
    max_raw_lines: int = 50
    include_pattern_hints: bool = True
    include_fix_hints: bool = False
    test_detail: Literal["full", "delta", "summary"] = "delta"
    error_detail: Literal["full", "compressed", "minimal"] = "compressed"
    build_detail: Literal["full", "status_only"] = "status_only"
    passthrough_on_error: bool = True
    max_compression_ratio: float = 0.95
    track_stats: bool = True
    generic_head_lines: int = 20
    generic_tail_lines: int = 20
    generic_dedup_threshold: int = 3
