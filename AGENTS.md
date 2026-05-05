# Repo Notes

## Verification Commands

When running tests, benchmarks, linters, builds, or similar verification commands in this repo, run them through Sieve so the agent sees compressed tool output:

```bash
PYTHONPATH=src python3 scripts/sieved_run.py -- <command>
```

Examples:

```bash
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 scripts/sieved_run.py -- python3 -m benchmarks.run
```

Do not use baseline mode by default.

## Plain Shell Commands

Use normal shell commands for repository inspection and file reading, such as `rg`, `sed`, `git diff`, `git status`, and `ls`.
