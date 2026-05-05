# agent-compress: Technical Specification

## Transparent feedback compression middleware for LLM coding agents

---

## 1. Problem Statement

83.9% of tokens in coding agent trajectories are observations — raw tool output flowing back from the environment (JetBrains/NeurIPS 2025). Agents re-consume this output in full on every subsequent turn due to conversation history accumulation, creating a token snowball where a single verbose test output compounds across 20+ turns.

Current agents treat tool output as opaque strings. No production system parses, structures, deduplicates, or diffs environment feedback before it enters the LLM context.

**Target:** Reduce observation tokens by 60–80% with zero accuracy degradation, delivered as a drop-in middleware layer compatible with any agent framework.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    LLM CODING AGENT                     │
│           (Claude Code / OpenHands / Aider)             │
└────────────────────────┬────────────────────────────────┘
                         │ tool_call(command)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   agent-compress                        │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │ Executor │→ │ Parser Router│→ │ Session State      │ │
│  │          │  │              │  │                    │ │
│  │ Runs the │  │ Detects tool │  │ - Previous outputs │ │
│  │ command  │  │ type, routes │  │ - Seen errors      │ │
│  │ verbatim │  │ to parser    │  │ - Read files       │ │
│  └──────────┘  └──────┬───────┘  │ - Test states      │ │
│                       │          └─────────┬─────────┘ │
│                       ▼                    │           │
│  ┌─────────────────────────────────────────┘           │
│  │                                                     │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐     │
│  │  │  Compiler  │ │   Test     │ │   Build    │     │
│  │  │  Parser    │ │  Parser    │ │  Parser    │     │
│  │  │            │ │            │ │            │     │
│  │  │ gcc/clang  │ │ pytest     │ │ pip/npm    │     │
│  │  │ rustc      │ │ jest       │ │ cargo      │     │
│  │  │ tsc        │ │ go test    │ │ make       │     │
│  │  │ javac      │ │ unittest   │ │ gradle     │     │
│  │  │ mypy       │ │ mocha      │ │ docker     │     │
│  │  │ pylint     │ │ rspec      │ │            │     │
│  │  │ eslint     │ │ pytest-cov │ │            │     │
│  │  └────────────┘ └────────────┘ └────────────┘     │
│  │                                                     │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐     │
│  │  │   File     │ │  Runtime   │ │  Generic   │     │
│  │  │  Parser    │ │  Parser    │ │  Fallback  │     │
│  │  │            │ │            │ │            │     │
│  │  │ find/ls    │ │ python tb  │ │ line count │     │
│  │  │ grep/rg    │ │ node err   │ │ truncation │     │
│  │  │ cat/head   │ │ segfault   │ │ dedup      │     │
│  │  │ tree       │ │ OOM        │ │            │     │
│  │  └────────────┘ └────────────┘ └────────────┘     │
│  │                                                     │
│  └──────┬──────────────────────────────────────────────┘
│         ▼                                               │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │  Delta Engine │→ │  Formatter   │                    │
│  │              │  │              │                    │
│  │ Diffs against│  │ Outputs      │                    │
│  │ session state│  │ compressed   │                    │
│  │              │  │ result       │                    │
│  └──────────────┘  └──────────────┘                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
                         │
                         │ compressed_output
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    LLM CODING AGENT                     │
│              (sees clean, minimal feedback)              │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Core Components

### 3.1 Executor

Runs the agent's command verbatim. Captures stdout, stderr, and exit code. No modification to execution — agent-compress is observation-only, never alters the command.

```python
@dataclass
class RawExecution:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timestamp: float
```

### 3.2 Parser Router

Classifies the tool output and routes to the appropriate domain parser. Classification uses a priority chain:

1. **Command pattern matching** — `pytest`, `npm test`, `cargo build`, etc.
2. **Output signature detection** — recognizes output patterns even when commands are wrapped (e.g., `bash -c "pytest ..."`)
3. **Generic fallback** — if no parser matches, apply line-count-based truncation and deduplication

```python
class ParserRouter:
    """Routes raw execution output to domain-specific parsers."""

    def __init__(self):
        self.parsers: list[tuple[ParserMatcher, OutputParser]] = [
            (PytestMatcher(),    PytestParser()),
            (JestMatcher(),      JestParser()),
            (GccMatcher(),       GccParser()),
            (RustcMatcher(),     RustcParser()),
            (TscMatcher(),       TscParser()),
            (MypyMatcher(),      MypyParser()),
            (EslintMatcher(),    EslintParser()),
            (PipMatcher(),       PipParser()),
            (NpmMatcher(),       NpmParser()),
            (CargoMatcher(),     CargoParser()),
            (FindMatcher(),      FindParser()),
            (GrepMatcher(),      GrepParser()),
            (PythonTBMatcher(),  PythonTracebackParser()),
            (NodeErrorMatcher(), NodeErrorParser()),
        ]
        self.fallback = GenericParser()

    def route(self, execution: RawExecution) -> OutputParser:
        for matcher, parser in self.parsers:
            if matcher.matches(execution):
                return parser
        return self.fallback
```

### 3.3 Domain Parsers

Each parser implements a common interface:

```python
class OutputParser(Protocol):
    def parse(self, execution: RawExecution) -> StructuredOutput: ...

@dataclass
class StructuredOutput:
    """Universal structured representation of tool output."""
    tool_type: str               # "pytest", "gcc", "pip", etc.
    status: Status               # SUCCESS, FAILURE, ERROR, TIMEOUT
    summary: str                 # One-line human-readable summary
    items: list[OutputItem]      # Structured error/warning/info items
    raw_line_count: int          # Original output size
    compressed_line_count: int   # After compression
    metadata: dict               # Parser-specific extra data
```

#### 3.3.1 Test Parser (pytest example)

**Input (typical raw pytest output — 847 tokens):**
```
============================= test session starts ==============================
platform linux -- Python 3.12.0, pytest-8.1.1, pluggy-1.4.0
rootdir: /home/user/project
configfile: pyproject.toml
plugins: django-4.8.0, cov-4.1.0, xdist-3.5.0
collected 142 items

tests/test_models.py ..............................                       [ 21%]
tests/test_views.py ...........F..F.......                               [ 35%]
tests/test_serializers.py ......................                          [ 50%]
tests/test_api.py ...............................                        [ 72%]
tests/test_utils.py ........................................             [100%]

=================================== FAILURES ===================================
________________________________ test_user_update ________________________________

    def test_user_update(self):
        user = UserFactory()
        response = self.client.patch(
            f"/api/users/{user.id}/",
            data={"name": "New Name"},
            format="json",
        )
>       assert response.status_code == 200
E       AssertionError: assert 403 == 200

tests/test_views.py:89: AssertionError
________________________________ test_user_delete ________________________________

    def test_user_delete(self):
        user = UserFactory()
        response = self.client.delete(f"/api/users/{user.id}/")
>       assert response.status_code == 204
E       AssertionError: assert 403 == 204

tests/test_views.py:102: AssertionError
=========================== short test summary info ============================
FAILED tests/test_views.py::TestUserViewSet::test_user_update - AssertionError
FAILED tests/test_views.py::TestUserViewSet::test_user_delete - AssertionError
========================= 2 failed, 140 passed, 0 warnings ====================
```

**Output (compressed — 127 tokens):**
```
PYTEST: 2 failed, 140 passed (142 total)

FAIL test_views.py::test_user_update (line 89)
  assert response.status_code == 200 → got 403

FAIL test_views.py::test_user_delete (line 102)
  assert response.status_code == 204 → got 403

Pattern: both failures are 403 (permission denied) in UserViewSet
```

**On subsequent run after fix (delta mode — 34 tokens):**
```
PYTEST DELTA: test_user_update now PASSES
Still failing: test_user_delete (line 102) — same 403 error
Result: 1 failed, 141 passed
```

#### 3.3.2 Compiler Parser (gcc/clang example)

**Input (typical gcc error — 312 tokens):**
```
src/parser.c: In function 'parse_expression':
src/parser.c:147:23: error: incompatible types when assigning to type
  'struct Node *' from type 'int'
  147 |     node->left = parse_term();
      |                       ^~~~~~~~~~~~
src/parser.c:147:23: note: expected 'struct Node *' but argument is of
  type 'int'
In file included from src/parser.c:3:
include/ast.h:24:5: note: expected 'struct Node *' but got 'int' due to
  implicit declaration
  24 |     struct Node *left;
     |     ^~~~~~~~~~~
src/parser.c:12:1: note: previous implicit declaration of 'parse_term'
  was here
  12 | int result = parse_term();
     | ^~~
```

**Output (compressed — 58 tokens):**
```
GCC ERROR in src/parser.c:147 (parse_expression)
  Type mismatch: assigning 'int' to 'struct Node *'
  Cause: parse_term() implicitly declared as int (missing #include or forward decl)
  Related: include/ast.h:24 defines left as 'struct Node *'
```

#### 3.3.3 Build/Install Parser (pip example)

**Input (typical pip install — 2,400+ tokens of download/install progress)**

**Output — success (12 tokens):**
```
PIP: installed 47 packages in 23.4s, no errors
```

**Output — failure (extracted, ~60 tokens):**
```
PIP FAIL: building wheel for psycopg2 (setup.py)
  Error: pg_config not found
  Fix: install libpq-dev (apt) or postgresql-devel (yum)
  All other packages installed successfully
```

#### 3.3.4 File Discovery Parser (find/grep/ls)

**Input (find . -name "*.py" — 300+ lines)**

**Output (compressed with relevance scoring):**
```
FIND: 287 .py files across 34 directories
Top-level structure:
  api/ (42 files), core/ (38 files), tests/ (67 files),
  utils/ (12 files), migrations/ (89 files, likely irrelevant)
```

#### 3.3.5 Runtime Error Parser (Python traceback)

**Input (full Python traceback — 180 tokens of frame stack)**

**Output (compressed — 52 tokens):**
```
RUNTIME ERROR: TypeError in api/views.py:67 (UserViewSet.update)
  'NoneType' has no attribute 'email'
  Call chain: views.py:67 → serializers.py:34 → models.py:112
  Variable: user = User.objects.filter(...).first()  # returns None
```

#### 3.3.6 Generic Fallback Parser

For unrecognized output:

```python
class GenericParser(OutputParser):
    """Handles unrecognized tool output with size-based strategies."""

    MAX_LINES = 50
    DEDUP_THRESHOLD = 3  # collapse 3+ identical lines

    def parse(self, execution: RawExecution) -> StructuredOutput:
        lines = execution.combined_output.splitlines()

        if len(lines) <= self.MAX_LINES:
            return StructuredOutput(
                tool_type="generic",
                status=self._infer_status(execution),
                summary=f"Output: {len(lines)} lines",
                raw_content=execution.combined_output,  # pass through
            )

        # Deduplicate repeated lines
        deduped = self._dedup(lines)

        # Keep first 20 + last 20, summarize middle
        if len(deduped) > self.MAX_LINES:
            head = deduped[:20]
            tail = deduped[-20:]
            omitted = len(deduped) - 40
            compressed = head + [f"[... {omitted} lines omitted ...]"] + tail
        else:
            compressed = deduped

        return StructuredOutput(
            tool_type="generic",
            status=self._infer_status(execution),
            summary=f"Output: {len(lines)} lines → {len(compressed)} lines",
            raw_content="\n".join(compressed),
        )
```

### 3.4 Session State

The session maintains a rolling record of observations across turns, enabling delta computation and deduplication.

```python
class SessionState:
    """Tracks observation history for cross-turn compression."""

    def __init__(self):
        self.turn: int = 0
        self.test_results: dict[str, TestResult] = {}    # test_id → last result
        self.seen_errors: list[ErrorSignature] = []       # deduplicated error log
        self.read_files: dict[str, FileSnapshot] = {}     # path → (hash, turn_read)
        self.build_status: BuildStatus | None = None
        self.token_stats: TokenStats = TokenStats()       # running compression metrics

    def advance_turn(self):
        self.turn += 1

    def get_test_delta(self, current: list[TestResult]) -> TestDelta:
        """Compare current test results against last known state."""
        delta = TestDelta()
        for test in current:
            prev = self.test_results.get(test.id)
            if prev is None:
                delta.new_tests.append(test)
            elif prev.status != test.status:
                delta.changed_tests.append((prev, test))
            # Unchanged tests are omitted entirely
        self.test_results.update({t.id: t for t in current})
        return delta

    def is_error_seen(self, error: ErrorSignature) -> tuple[bool, int | None]:
        """Check if this exact error was seen before, return turn number."""
        for i, seen in enumerate(self.seen_errors):
            if seen.matches(error):
                return True, seen.first_seen_turn
        self.seen_errors.append(error)
        error.first_seen_turn = self.turn
        return False, None

    def is_file_unchanged(self, path: str, content_hash: str) -> tuple[bool, int | None]:
        """Check if file content matches what was read previously."""
        if path in self.read_files:
            snap = self.read_files[path]
            if snap.hash == content_hash:
                return True, snap.turn_read
        self.read_files[path] = FileSnapshot(hash=content_hash, turn_read=self.turn)
        return False, None


@dataclass
class ErrorSignature:
    """Fingerprint for deduplication. Ignores line numbers (which shift)."""
    error_type: str      # "TypeError", "E0308", etc.
    file: str
    message_hash: str    # hash of normalized error message
    first_seen_turn: int = 0

    def matches(self, other: "ErrorSignature") -> bool:
        return (
            self.error_type == other.error_type
            and self.file == other.file
            and self.message_hash == other.message_hash
        )
```

### 3.5 Delta Engine

Operates after parsing, before formatting. Compares structured output against session state to produce minimal deltas.

```python
class DeltaEngine:
    """Reduces structured output by diffing against session history."""

    def compress(
        self, parsed: StructuredOutput, session: SessionState
    ) -> CompressedOutput:
        session.advance_turn()

        if parsed.tool_type in ("pytest", "jest", "go_test", "unittest"):
            return self._compress_tests(parsed, session)
        elif parsed.tool_type in ("gcc", "rustc", "tsc", "javac", "mypy"):
            return self._compress_errors(parsed, session)
        elif parsed.tool_type in ("pip", "npm", "cargo_build"):
            return self._compress_build(parsed, session)
        else:
            return self._compress_generic(parsed, session)

    def _compress_tests(
        self, parsed: StructuredOutput, session: SessionState
    ) -> CompressedOutput:
        current_results = parsed.test_results
        delta = session.get_test_delta(current_results)

        if not delta.has_changes and session.turn > 1:
            # Tests ran identically to last time
            return CompressedOutput(
                content=f"TESTS UNCHANGED: {parsed.summary}",
                compression_ratio=0.95,
            )

        # Build delta-only output
        lines = [f"TEST DELTA (turn {session.turn}):"]
        for prev, curr in delta.changed_tests:
            if curr.passed and not prev.passed:
                lines.append(f"  ✓ {curr.id} now PASSES")
            elif not curr.passed and prev.passed:
                lines.append(f"  ✗ {curr.id} now FAILS: {curr.short_error}")
            else:
                lines.append(f"  ~ {curr.id}: error changed → {curr.short_error}")

        for test in delta.new_tests:
            status = "✓" if test.passed else "✗"
            lines.append(f"  {status} {test.id} (new)")

        # Always include summary line
        lines.append(f"Total: {parsed.summary}")
        return CompressedOutput(
            content="\n".join(lines),
            compression_ratio=1 - len("\n".join(lines)) / len(parsed.raw_content),
        )

    def _compress_errors(
        self, parsed: StructuredOutput, session: SessionState
    ) -> CompressedOutput:
        lines = []
        for error in parsed.items:
            seen, turn = session.is_error_seen(error.signature)
            if seen:
                lines.append(
                    f"  [same as turn {turn}] {error.file}:{error.line} — {error.error_type}"
                )
            else:
                lines.append(error.compressed_repr)

        header = f"{parsed.tool_type.upper()}: {len(parsed.items)} error(s)"
        return CompressedOutput(
            content=header + "\n" + "\n".join(lines),
            compression_ratio=1 - len(header + "\n".join(lines)) / len(parsed.raw_content),
        )
```

### 3.6 Formatter

Converts `CompressedOutput` into the final string returned to the agent. Supports multiple output styles:

```python
class OutputFormat(Enum):
    PLAIN = "plain"          # Human-readable compressed text (default)
    STRUCTURED = "structured" # JSON for agents that prefer structured data
    XML = "xml"              # XML tags for Claude-style agents
    MINIMAL = "minimal"      # Absolute minimum — errors only, no context


class Formatter:
    def format(self, compressed: CompressedOutput, fmt: OutputFormat) -> str:
        if fmt == OutputFormat.PLAIN:
            return compressed.content

        elif fmt == OutputFormat.STRUCTURED:
            return json.dumps({
                "tool": compressed.tool_type,
                "status": compressed.status.value,
                "summary": compressed.summary,
                "items": [item.to_dict() for item in compressed.items],
                "compression": f"{compressed.compression_ratio:.0%}",
            }, indent=2)

        elif fmt == OutputFormat.XML:
            return f"""<tool_result tool="{compressed.tool_type}" status="{compressed.status.value}">
<summary>{compressed.summary}</summary>
{chr(10).join(f'<item type="{i.type}">{i.compressed_repr}</item>' for i in compressed.items)}
</tool_result>"""

        elif fmt == OutputFormat.MINIMAL:
            if compressed.status == Status.SUCCESS:
                return compressed.summary
            return "\n".join(
                item.compressed_repr
                for item in compressed.items
                if item.severity == Severity.ERROR
            )
```

---

## 4. Integration API

### 4.1 Direct wrapping (simplest)

```python
from agent_compress import CompressSession

session = CompressSession()

# Agent issues a tool call
raw_output = subprocess.run(["pytest", "tests/"], capture_output=True, text=True)

# Compress before returning to LLM
compressed = session.compress(
    command="pytest tests/",
    stdout=raw_output.stdout,
    stderr=raw_output.stderr,
    exit_code=raw_output.returncode,
)

# Send compressed.text to the LLM instead of raw output
# compressed.stats shows token savings
```

### 4.2 As a tool wrapper (drop-in for agent frameworks)

```python
from agent_compress import wrap_tool

@wrap_tool
def execute_bash(command: str) -> str:
    """The decorator intercepts the return value and compresses it.
    Session state is maintained automatically across calls."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr
```

### 4.3 As MCP server middleware

```python
from agent_compress import CompressMCPProxy

# Wraps an existing MCP server, compressing all tool results
proxy = CompressMCPProxy(
    upstream="stdio://mcp-server-bash",
    config=CompressConfig(
        format=OutputFormat.PLAIN,
        delta_mode=True,
        max_raw_lines=50,
    )
)
proxy.serve()  # Exposes same tools as upstream, with compressed output
```

### 4.4 Configuration

```python
@dataclass
class CompressConfig:
    # Output format
    format: OutputFormat = OutputFormat.PLAIN

    # Delta compression
    delta_mode: bool = True              # Enable cross-turn deduplication
    max_history_turns: int = 20          # How far back to track state

    # Parser behavior
    max_raw_lines: int = 50              # Fallback truncation threshold
    include_pattern_hints: bool = True   # Add "Pattern: ..." annotations
    include_fix_hints: bool = False      # Add suggested fixes (costs tokens)

    # Granularity controls
    test_detail: Literal["full", "delta", "summary"] = "delta"
    error_detail: Literal["full", "compressed", "minimal"] = "compressed"
    build_detail: Literal["full", "status_only"] = "status_only"

    # Safety
    passthrough_on_error: bool = True    # If parser fails, return raw output
    max_compression_ratio: float = 0.95  # Never compress more than 95%

    # Telemetry
    track_stats: bool = True             # Collect compression statistics
```

---

## 5. Data Model

```python
# --- Core output items ---

@dataclass
class TestResult:
    id: str                    # "test_views.py::TestUserViewSet::test_user_update"
    status: Literal["passed", "failed", "error", "skipped"]
    file: str
    line: int | None
    assertion: str | None      # "assert 200 == 403"
    actual: str | None         # "403"
    expected: str | None       # "200"
    duration_ms: float | None

@dataclass
class CompilerError:
    severity: Literal["error", "warning", "note", "info"]
    file: str
    line: int
    column: int | None
    code: str | None           # "E0308", "TS2345", etc.
    message: str               # Normalized, one-line
    context_line: str | None   # The source line with the error
    signature: ErrorSignature  # For dedup

@dataclass
class RuntimeError:
    error_type: str            # "TypeError", "ValueError", etc.
    message: str
    file: str
    line: int
    function: str | None
    call_chain: list[str]      # ["views.py:67", "serializers.py:34", "models.py:112"]
    variable_hint: str | None  # "user = None" extracted from frame locals

@dataclass
class BuildResult:
    tool: str                  # "pip", "npm", "cargo"
    success: bool
    packages_installed: int
    duration_s: float
    failure_detail: str | None # Only populated on failure

# --- Compression metrics ---

@dataclass
class TokenStats:
    total_raw_chars: int = 0
    total_compressed_chars: int = 0
    turns_processed: int = 0
    delta_hits: int = 0        # Times delta compression saved output
    dedup_hits: int = 0        # Times error dedup saved output

    @property
    def compression_ratio(self) -> float:
        if self.total_raw_chars == 0:
            return 0
        return 1 - self.total_compressed_chars / self.total_raw_chars

    @property
    def estimated_token_savings(self) -> int:
        """Rough estimate: 1 token ≈ 4 chars."""
        return (self.total_raw_chars - self.total_compressed_chars) // 4
```

---

## 6. Testing Strategy

### 7.1 Parser unit tests

Each parser gets a corpus of real-world outputs collected from:
- SWE-bench task replays (pytest, Python tracebacks)
- Open-source CI logs (GitHub Actions artifacts)
- Synthetic error generation (compile random broken code)

Test structure:
```python
def test_pytest_parser_extracts_failures():
    raw = load_fixture("pytest_2_failures_140_passed.txt")
    parsed = PytestParser().parse(make_execution(raw))

    assert parsed.status == Status.FAILURE
    assert len(parsed.items) == 2
    assert parsed.items[0].file == "tests/test_views.py"
    assert parsed.items[0].line == 89
    assert parsed.items[0].actual == "403"
    assert parsed.items[0].expected == "200"
    assert len(parsed.raw_content) / len(raw) < 0.2  # >80% compression
```

### 7.2 Integration tests with real agents

Replay SWE-bench trajectories with and without agent-compress. Measure:
- Total tokens consumed (input + output)
- Task solve rate (must not decrease)
- Number of interaction turns (may decrease)
- Wall-clock time (may decrease due to smaller context)

### 7.3 Compression benchmarks

A standardized benchmark of 500 real tool outputs (100 per category: test, compiler, build, runtime, misc) with measured compression ratios and round-trip fidelity (can the original error be reconstructed from the compressed version?).

---

## 7. File Structure

```
agent-compress/
├── pyproject.toml
├── README.md
├── src/
│   └── agent_compress/
│       ├── __init__.py           # Public API: CompressSession, wrap_tool
│       ├── core.py               # RawExecution, StructuredOutput, CompressedOutput
│       ├── config.py             # CompressConfig, OutputFormat
│       ├── router.py             # ParserRouter
│       ├── session.py            # SessionState, ErrorSignature
│       ├── delta.py              # DeltaEngine
│       ├── formatter.py          # Formatter
│       ├── stats.py              # TokenStats, compression telemetry
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── mcp.py            # CompressMCPProxy
│       │   ├── openai.py         # OpenAI function-call wrapper
│       │   └── anthropic.py      # Anthropic tool-use wrapper
│       └── parsers/
│           ├── __init__.py
│           ├── base.py           # OutputParser protocol, ParserMatcher
│           ├── pytest_.py        # pytest output parser
│           ├── python_tb.py      # Python traceback parser
│           ├── gcc.py            # gcc/clang error parser
│           ├── tsc.py            # TypeScript compiler
│           ├── eslint.py         # ESLint output
│           ├── mypy.py           # mypy type checker
│           ├── jest.py           # Jest test runner
│           ├── pip_.py           # pip install output
│           ├── npm.py            # npm install/build
│           ├── cargo.py          # cargo build/test
│           ├── find_.py          # find/ls/tree output
│           ├── grep_.py          # grep/ripgrep output
│           ├── runtime.py        # Python/Node runtime errors
│           └── generic.py        # Fallback parser
├── tests/
│   ├── fixtures/                 # Real-world output samples
│   │   ├── pytest/
│   │   ├── gcc/
│   │   ├── pip/
│   │   └── ...
│   ├── test_parsers/
│   ├── test_session.py
│   ├── test_delta.py
│   ├── test_integration.py
│   └── test_benchmarks.py
└── benchmarks/
    ├── corpus/                   # 500-sample benchmark set
    ├── run_benchmark.py
    └── results/
```

---

## 8. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Observation token reduction | ≥60% average | Across SWE-bench Verified replay |
| Task accuracy | ≥ baseline | Same tasks, same model, with/without compression |
| Parser coverage | ≥80% of tool calls | Percentage of outputs matched by a domain parser |
| Latency overhead | <10ms per call | Parsing + compression time |
| Integration effort | <10 lines of code | To add to existing agent framework |
