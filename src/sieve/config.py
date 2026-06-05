from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OutputFormat(str, Enum):
    PLAIN = "plain"
    STRUCTURED = "structured"
    XML = "xml"
    MINIMAL = "minimal"


@dataclass(slots=True)
class CompressConfig:
    format: OutputFormat = OutputFormat.PLAIN
    delta_mode: bool = True
    max_raw_lines: int = 50
    include_pattern_hints: bool = True
    passthrough_on_error: bool = True
    track_stats: bool = True
    generic_head_lines: int = 20
    generic_tail_lines: int = 20
    generic_dedup_threshold: int = 3
