from __future__ import annotations

from typing import Protocol

from sieve.core import RawExecution, StructuredOutput


class OutputParser(Protocol):
    tool_type: str

    def supports(self, execution: RawExecution) -> bool: ...

    def parse(self, execution: RawExecution) -> StructuredOutput: ...
