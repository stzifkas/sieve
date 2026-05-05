from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TokenStats:
    total_raw_chars: int = 0
    total_compressed_chars: int = 0
    turns_processed: int = 0
    delta_hits: int = 0
    dedup_hits: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.total_raw_chars == 0:
            return 0.0
        return 1 - self.total_compressed_chars / self.total_raw_chars

    @property
    def estimated_token_savings(self) -> int:
        return (self.total_raw_chars - self.total_compressed_chars) // 4
