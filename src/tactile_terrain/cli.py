"""Command line entry point. Thin wrapper; real work lives in api.py."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tactile-terrain", description="Tactile terrain printing."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="Run the MCP server.")
    sub.add_parser("build", help="Build a model from a spec.")
    sub.add_parser("doctor", help="Check the installation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"{args.command}: not implemented yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
