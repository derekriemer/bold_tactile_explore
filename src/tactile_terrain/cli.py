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
    build = sub.add_parser("build", help="Build a model from a spec.")
    build.add_argument("spec", help="Path to a spec JSON file.")
    build.add_argument("--overwrite", action="store_true", help="Rebuild an existing model.")
    sub.add_parser("doctor", help="Check the installation.")
    sub.add_parser(
        "dev-plugin", help="Build the local development plugin (git-ignored, never published)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # arrows and accents survive Windows consoles
    args = build_parser().parse_args(argv)
    if args.command == "build":
        from tactile_terrain import api
        from tactile_terrain.spec import load_spec

        print(api.build_spec(load_spec(args.spec), overwrite=args.overwrite))
        return 0
    if args.command == "mcp":
        from tactile_terrain.server import run

        run()
        return 0
    if args.command == "doctor":
        from tactile_terrain import api

        print(api.doctor())
        return 0
    if args.command == "dev-plugin":
        from pathlib import Path

        from tactile_terrain.devkit.plugin import build_dev_plugin

        repo = Path(__file__).resolve().parents[2]
        print(f"Built {build_dev_plugin(repo)}")
        return 0
    print(f"{args.command}: not implemented yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
