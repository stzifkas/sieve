from __future__ import annotations

from sieve.config import CompressConfig
from sieve.core import RawExecution, StructuredOutput
from sieve.parsers import (
    EslintParser,
    GccParser,
    GenericParser,
    MypyParser,
    PipParser,
    PytestParser,
    PythonTracebackParser,
    TscParser,
)
from sieve.parsers.base import OutputParser


class ParserRouter:
    def __init__(self, config: CompressConfig):
        # Order matters: more specific matchers first. Pytest before generic
        # Python traceback (a failing pytest run also contains a traceback).
        # Mypy before gcc — both share the file:line:col: error: shape, but
        # mypy lines have a trailing [code] tag we use to disambiguate.
        self.parsers: list[OutputParser] = [
            PytestParser(config),
            PipParser(config),
            EslintParser(config),
            TscParser(config),
            MypyParser(config),
            GccParser(config),
            PythonTracebackParser(config),
        ]
        self.fallback = GenericParser(config)

    def route(self, execution: RawExecution) -> OutputParser:
        for parser in self.parsers:
            if parser.supports(execution):
                return parser
        return self.fallback

    def parse(self, execution: RawExecution) -> StructuredOutput:
        parser = self.route(execution)
        return parser.parse(execution)
