# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-05

First public release of **Sieve** (`agent-sieve`) — transparent feedback
compression middleware for LLM coding agents.

### Added

- Core compression library (`sieve.CompressSession`, `wrap_tool`) with a
  never-larger-than-raw invariant and cross-turn delta deduplication.
- Parser suite: pytest, Python traceback, mypy, tsc, eslint, gcc/clang, pip,
  and a generic fallback.
- Output formats: plain, structured (JSON), XML, and minimal.
- `sieve` CLI with `run` and `config` subcommands, plus the `sieve-run`
  console script for wrapping a subprocess.
- `sieve config claude` / `sieve config cursor` to install, uninstall, and
  inspect agent harness hooks (dry-run by default, `--write` to apply, with
  automatic backups).
- Agent harness hooks: `sieve-hook-claude` (Claude Code `PreToolUse`) and
  `sieve-hook-cursor` (Cursor `preToolUse`).
- MCP proxy (`sieve.integrations.mcp`, `mcp` extra) that compresses every
  `TextContent` block from an upstream MCP server.
- Benchmarks: fixture-corpus compression report, SWE-bench Lite paired
  baseline-vs-sieve runners (Cursor / Codex), and CI-Repair-Bench.

[Unreleased]: https://github.com/stzifkas/sieve/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/stzifkas/sieve/releases/tag/v0.1.0
