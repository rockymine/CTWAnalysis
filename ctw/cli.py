"""CTW Analysis Toolkit — CLI parser construction and entry point."""

import argparse
import os

from ctw.common import PROJECT_ROOT
from ctw.commands import run, layout, islands, xml, info, docs, matches, maps, debug, db


def build_parser() -> tuple[argparse.ArgumentParser, argparse.Action]:
    """Build the argument parser with all subcommands.

    Returns:
        (parser, subparsers_action) — the subparsers action is exposed so
        that the config system can set defaults before the final parse.
    """

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
  python ctw.py info --map segment
  python ctw.py info --map segment --json
""",
    )
    parser.add_argument(
        '--config',
        help='Path to YAML config file (default: ctw_config.yaml in working directory)',
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
    info.register(subparsers, map_parent)
    docs.register(subparsers)
    matches.register(subparsers)
    maps.register(subparsers)
    debug.register(subparsers)
    db.register(subparsers)

    return parser, subparsers


def main():
    os.chdir(PROJECT_ROOT)
    parser, subparsers = build_parser()

    # Load YAML config and inject values as parser defaults
    # (before the real parse, so CLI arguments still take priority).
    from ctw.config import find_config_arg, load_config, apply_config_to_parsers

    config = load_config(find_config_arg())
    if config:
        apply_config_to_parsers(subparsers, config)

    args = parser.parse_args()
    if not hasattr(args, 'func'):
        # Subcommand given without action (e.g. "matches" with no action)
        parser.parse_args([args.command, '--help'])
        return
    args.func(args)
