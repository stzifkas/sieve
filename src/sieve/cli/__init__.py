"""Console entry points for the ``sieve`` CLI."""

from __future__ import annotations

import argparse
import sys

from . import config as config_cmd
from . import run as run_cmd


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="sieve",
        description="Transparent feedback compression middleware for LLM coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run",
        help="Execute a command and emit compressed agent-facing output (alias of sieve-run).",
        add_help=False,
    )
    p_run.set_defaults(handler=lambda rest: run_cmd.main(rest))

    p_config = sub.add_parser("config", help="Configure agent integrations.")
    config_cmd.register(p_config)

    if not argv:
        parser.print_help()
        return 2

    head, *rest = argv
    if head == "run":
        return run_cmd.main(rest)

    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
