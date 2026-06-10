## What & why

<!-- One or two sentences. Link the issue if there is one. -->

## Verification

<!-- Paste the commands you ran and a summary of their output. Minimum:
uv run python -m unittest discover -s tests -v
uv run python -m benchmarks.run -->

## Checklist

- [ ] Tests pass locally and new behavior has coverage
- [ ] Never-larger-than-raw invariant preserved (plain format)
- [ ] Parser changes include fixtures for noisy/edge output
- [ ] Docs updated if user-facing behavior changed
