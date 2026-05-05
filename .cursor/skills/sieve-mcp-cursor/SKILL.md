---
name: sieve-mcp-cursor
description: >-
  Installs and wires the Sieve MCP compressing proxy (`sieve.integrations.mcp`)
  for Cursor. Use when the user wants Cursor MCP setup, MCP proxy configuration,
  or wrapping an upstream like `@modelcontextprotocol/server-everything` or
  `server-filesystem` (there is no `server-bash` on npm).
disable-model-invocation: false
---

# Sieve MCP in Cursor

**MCP stays the integration.** This skill only makes setup repeatable: deps, exact launch shape, and where to paste config. The proxy still runs as a normal stdio MCP server; Cursor starts it like any other MCP server.

## What gets easier

- One place for **copy-paste** `command` / `args` / `cwd`.
- Agent can **run `uv sync`** in repo root and **draft MCP JSON** for the user’s paths.

## Prerequisites

- Repo checkout (this project).
- **Python ≥ 3.11**, **`uv`** recommended (or another way to install `.[mcp]`).
- Upstream server deps as needed (e.g. **Node + `npx`** for official `@modelcontextprotocol/server-*` packages).

## Install deps (repo root)

```bash
cd /path/to/agent_compress
uv sync
```

(`dev` group includes `mcp`; core package is `sieve` under `src/sieve/`.)

## Cursor MCP server shape

Launch pattern:

```text
<python-or-uv> … -m sieve.integrations.mcp -- <upstream-command> [upstream-args…]
```

Everything after `--` is the **upstream** MCP process (what you would run without Sieve).

### Recommended: `uv run` + repo `cwd`

Set **working directory** to the repository root so `uv` resolves this project.

**Command:** `uv`  
**Args:**

```text
run
python
-m
sieve.integrations.mcp
--
npx
-y
@modelcontextprotocol/server-everything
```

Adjust the segment after `--` for another upstream (filesystem MCP, custom server, etc.).

### Alternative: venv `python`

After `uv sync`, use `$(uv run which python)` as **command** with args:

```text
-m
sieve.integrations.mcp
--
…upstream…
```

Still use **cwd** = repo root unless the env is global.

## Claude Desktop–style JSON (many Cursor builds accept this)

Replace `REPO_ROOT` with the absolute path to this repository.

```json
{
  "mcpServers": {
    "sieve-demo": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "sieve.integrations.mcp",
        "--",
        "npx",
        "-y",
        "@modelcontextprotocol/server-everything"
      ],
      "cwd": "REPO_ROOT"
    }
  }
}
```

If Cursor’s MCP UI only exposes fields (no raw JSON), map **command** → `command`, **args** → array order above, **cwd** → repo root.

## Verify

1. Restart MCP / reload Cursor after adding the server.
2. Invoke a tool that returns **large text**; compare size or readability with the same upstream **without** the proxy (optional A/B).

## Agent checklist

- [ ] `uv sync` from repo root (or confirm editable install with `mcp` extra).
- [ ] MCP entry uses `-m sieve.integrations.mcp`, then `--`, then upstream.
- [ ] `cwd` points at repo root when using `uv run`.
- [ ] User has upstream prerequisites (e.g. Node for `npx` examples).

## Reference

- Implementation: `src/sieve/integrations/mcp.py`
- Human-facing overview: `README.md` (MCP proxy section)
