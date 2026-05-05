from __future__ import annotations

import time
from dataclasses import dataclass, replace
from functools import wraps
from typing import Any, Callable

from sieve.config import CompressConfig, OutputFormat
from sieve.core import CompressedOutput, RawExecution, StructuredOutput
from sieve.delta import DeltaEngine
from sieve.formatter import Formatter
from sieve.router import ParserRouter
from sieve.session import SessionState
from sieve.stats import TokenStats


@dataclass(slots=True)
class CompressionResult:
    text: str
    execution: RawExecution
    parsed: StructuredOutput
    compressed: CompressedOutput
    stats: TokenStats


class CompressSession:
    def __init__(
        self,
        config: CompressConfig | None = None,
        session_state: SessionState | None = None,
    ):
        self.config = config or CompressConfig()
        self.state = session_state or SessionState(track_stats=self.config.track_stats)
        self.router = ParserRouter(self.config)
        self.delta = DeltaEngine(self.config)
        self.formatter = Formatter()

    def compress(
        self,
        *,
        command: str,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        duration_ms: int = 0,
        timestamp: float | None = None,
        output_format: OutputFormat | None = None,
    ) -> CompressionResult:
        execution = RawExecution(
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        return self.compress_execution(execution, output_format=output_format)

    def compress_execution(
        self,
        execution: RawExecution,
        *,
        output_format: OutputFormat | None = None,
    ) -> CompressionResult:
        try:
            parsed = self.router.parse(execution)
            compressed = self.delta.compress(parsed, self.state)
            fmt = output_format or self.config.format
            text = self.formatter.format(compressed, fmt)
        except Exception:
            if not self.config.passthrough_on_error:
                raise
            raw_text = execution.combined_output
            parsed = StructuredOutput(
                tool_type="generic",
                status=self.router.fallback._infer_status(execution),
                summary="Passthrough: parser failure",
                raw_line_count=len(raw_text.splitlines()),
                compressed_line_count=len(raw_text.splitlines()),
                raw_content=raw_text,
            )
            compressed = CompressedOutput(
                tool_type="generic",
                status=parsed.status,
                summary=parsed.summary,
                content=raw_text,
                raw_chars=len(raw_text),
                compressed_chars=len(raw_text),
            )
            text = raw_text

        return CompressionResult(
            text=text,
            execution=execution,
            parsed=parsed,
            compressed=compressed,
            stats=replace(self.state.token_stats),
        )


def wrap_tool(
    func: Callable[..., Any] | None = None,
    *,
    session: CompressSession | None = None,
    config: CompressConfig | None = None,
    output_format: OutputFormat | None = None,
) -> Callable[..., str]:
    def decorator(inner: Callable[..., Any]) -> Callable[..., str]:
        active_session = session or CompressSession(config=config)

        @wraps(inner)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            result = inner(*args, **kwargs)
            command = _infer_command(inner, args, kwargs)
            stdout, stderr, exit_code = _coerce_tool_result(result)
            compressed = active_session.compress(
                command=command,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_format=output_format,
            )
            return compressed.text

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def _infer_command(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    command = kwargs.get("command")
    if isinstance(command, str):
        return command
    if args and isinstance(args[0], str):
        return args[0]
    return func.__name__


def _coerce_tool_result(result: Any) -> tuple[str, str, int]:
    if isinstance(result, RawExecution):
        return result.stdout, result.stderr, result.exit_code
    if isinstance(result, str):
        return result, "", 0
    if isinstance(result, tuple) and len(result) == 3:
        stdout, stderr, exit_code = result
        return str(stdout), str(stderr), int(exit_code)
    if hasattr(result, "stdout") and hasattr(result, "stderr") and hasattr(result, "returncode"):
        return str(result.stdout), str(result.stderr), int(result.returncode)
    raise TypeError(
        "wrap_tool expects the wrapped function to return a string, "
        "(stdout, stderr, exit_code), RawExecution, or CompletedProcess-like object."
    )
