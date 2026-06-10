# Sieve Roadmap

Sieve's promise is simple: **agents see less, but never less than they need.**
Everything on this roadmap serves one of three goals — make that promise
trustworthy in real sessions, cover the tools real projects actually run, and
back the claims with evidence.

Live progress is tracked in the pinned
[roadmap tracking issue (#18)](https://github.com/stzifkas/sieve/issues/18),
with every work item attached as a sub-issue. Contributions welcome — parser
issues in particular are designed to be self-contained.

## v0.2 — Trustworthy in real sessions

The library is solid; the rough edges are all at the boundary where Sieve
meets a live agent session. These are the items that decide whether someone
keeps Sieve installed after the first day.

- **Session-scoped state.** `.sieve/session.json` currently persists across
  unrelated agent conversations, so a fresh conversation can be greeted with
  `PYTEST DELTA: unchanged` referring to context the model has never seen.
  Scope state per agent session (Claude Code hooks receive a `session_id`),
  add a TTL, and a `sieve session reset` command.
- **Raw output on demand.** Lossy compression needs an audited escape hatch.
  Keep the last N raw outputs and expose `sieve raw last` so an agent (or
  human) can always recover the uncompressed text.
- **Honest error propagation in the MCP proxy.** Preserve the upstream
  `isError` flag instead of letting the SDK rebuild results as successes.
- **Robust escape hatch.** Replace substring-based `RAW_HINTS` matching
  (`pytest --raw-data` currently disables wrapping) with token-level matching
  and document the supported opt-outs.
- **Concurrency-safe session file.** Parallel `sieve-run` invocations
  currently race read-modify-write on the session file.
- **Token-aware metrics.** Report savings in tokens, not characters — that is
  the unit users are billed in.
- **`sieve stats`.** The per-session savings counters already exist
  internally; surface them.

## v0.3 — Cover what real projects run

Each missing parser is a chunk of agent context Sieve silently passes
through. Parsers are the easiest high-value contribution: one file, fixtures,
tests, no cross-cutting changes (see
[CONTRIBUTING.md](CONTRIBUTING.md#adding-or-updating-parsers)).

- **ruff** — already in the hook's noisy-command list, but routes to the
  generic fallback today.
- **jest / vitest** — the pytest of the JS world.
- **go test / go build**
- **cargo test / cargo build**
- **npm / yarn / pnpm install** — same shape of win as the pip parser (98.5%
  on the fixture corpus).
- **MCP proxy completeness** — forward resources, prompts, and notifications;
  propagate pagination cursors.
- **Platform coverage** — macOS and Windows CI runners; a mypy gate (the
  package ships `py.typed` but is never type-checked in CI).

## v0.4 — Evidence

The fixture-corpus numbers are methodologically clean but small; the
SWE-bench pilot is directional (N=4). Before claiming "saves X% at no
resolve-rate cost" in anything louder than a README caveat:

- Scale the paired SWE-bench Lite run to a meaningful N.
- Expand fixture coverage for the thin categories (mypy N=2, eslint N=1).
- Publish reproducible results with manifests and harness versions pinned.

## v0.5+ — Horizons

Scope expansion, deliberately sequenced after the trust and coverage work:
these change what Sieve *is* — from "output shrinker" to the deterministic
context layer between agents and their tools. Sieve's defensible asset is not
compression; it's deterministic parsing into structured items, a session-level
memory of what the model has already seen, and cross-turn deltas. Everything
here deepens those primitives, widens distribution, or builds retention.

**New DX primitives**

- **Zoomable tool output.** Every compressed item gets a stable inline ID;
  `sieve expand <id>` (CLI or MCP tool) returns the full raw block for just
  that item. Tool output becomes a progressive-disclosure tree, and the
  biggest objection to lossy compression becomes the signature feature.
- **File-read dedup.** Re-read files are among the largest observation-token
  sinks, and the primitive (`SessionState.read_files`) already exists unused
  in the codebase: answer repeat reads with "unchanged since turn N" or a
  diff against what the model last saw.
- **Budget-aware adaptive verbosity.** Verbosity as a policy function of
  repeat count and remaining context budget. This is also the positioning
  move against harness-native compaction: deterministic, inspectable,
  unit-testable degradation — nothing paraphrased by a model.

**Distribution wedges**

- **`sieve-action`.** A GitHub Action posting compressed CI-failure summaries
  as PR comments — valuable to humans and CI-repair agents alike, and every
  comment is an advertisement with a built-in proof point.
- **Framework adapters.** Idiomatic glue for the Claude Agent SDK, OpenAI
  Agents SDK, LangGraph, OpenHands, and Aider: one adapter ships Sieve to
  every app built on that framework.
- **Harness breadth.** Gemini CLI, Codex CLI, Copilot CLI, Zed — each hook
  adapter is small and widens the "works with your stack" claim.

**Enterprise & delight**

- **Secret/PII redaction.** Sieve already sits at the choke point between
  tools and the model; a deterministic scrubbing pass turns "compression
  middleware" into "context hygiene middleware" — the first thing an
  enterprise security review asks about.
- **Flaky-test detection.** The delta engine already sees pass/fail flips
  across turns; surfacing "likely flaky, don't chase it" prevents the most
  expensive agent failure mode (debugging nondeterminism for 20 turns).
- **Next-wave parsers.** Where agents are going, not just where they are:
  terraform plan, kubectl, Playwright/Cypress, docker build, Gradle/Maven —
  plus streaming compression for long-running builds as the prerequisite.

## Ongoing

- Release automation (PyPI trusted publishing on tag).
- A demo recording and an `examples/` directory.
- Savings telemetry worth showing a manager (weekly rollups, OTel export) as
  `sieve stats` matures.
- Keep the core dependency-free and the never-larger-than-raw invariant
  intact — both are load-bearing features, not accidents.

## Non-goals

- **Summarizing with an LLM.** Sieve is deterministic parsing, not a second
  model call. Predictable, fast, free, and testable beats occasionally
  smarter.
- **Compressing file reads / arbitrary tool output semantically.** The scope
  is *tool feedback* (tests, type-checkers, linters, builds, installs), where
  structure is known and fidelity is verifiable.
