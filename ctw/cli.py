"""CTW Analysis Toolkit — CLI parser construction and entry point."""

import argparse
import os

from ctw.common import PROJECT_ROOT
from ctw.commands import run, layout, islands, xml, match, info, docs, matches


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""

    # Shared parent for --map and --force
    map_parent = argparse.ArgumentParser(add_help=False)
    map_parent.add_argument(
        '--map', required=True,
        help='Map name (e.g., tumbleweed) or path to map folder',
    )
    map_parent.add_argument(
        '--force', action='store_true',
        help='Force regeneration of existing outputs',
    )

    # Top-level parser
    parser = argparse.ArgumentParser(
        prog='ctw',
        description='CTW Analysis Toolkit — Unified CLI for map and match analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ctw.py run --map tumbleweed --no-matches
  python ctw.py run --all --force --no-matches
  python ctw.py layout --map kanto
  python ctw.py islands --map segment --force
  python ctw.py xml --map aether --visualize
  python ctw.py match --map tumbleweed --match 2026-01-24_22-24-17_75.parquet
  python ctw.py info --map segment
  python ctw.py info --map segment --json
""",
    )
    subparsers = parser.add_subparsers(
        dest='command', required=True, metavar='<command>',
    )

    # Register each command module.
    # Commands that use the shared --map/--force parent receive map_parent;
    # commands that define their own flags (run, docs, matches) do not.
    run.register(subparsers)
    layout.register(subparsers, map_parent)
    islands.register(subparsers, map_parent)
    xml.register(subparsers, map_parent)
    match.register(subparsers, map_parent)
    info.register(subparsers, map_parent)
    docs.register(subparsers)
    matches.register(subparsers)

    return parser


def main():
    os.chdir(PROJECT_ROOT)
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, 'func'):
        # Subcommand given without action (e.g. "matches" with no action)
        parser.parse_args([args.command, '--help'])
        return
    args.func(args)
