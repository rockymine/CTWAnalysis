"""Hierarchical YAML configuration for the CTW CLI.

Priority (highest to lowest):
    1. CLI arguments
    2. YAML config file
    3. Internal argparse defaults

Config file discovery:
    1. --config <path>  (from CLI)
    2. ctw_config.yaml  (in working directory)
"""

import argparse
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Schema: section → key (underscore-normalized) → expected Python type
# ---------------------------------------------------------------------------
CONFIG_SCHEMA: dict[str, dict[str, type]] = {
    'global': {
        'force': bool,
        'plots': bool,
        'output': str,
    },
    'layout': {
        'threshold': int,
        'density_mode': str,
        'skip_y0': bool,
        'skip_surface': bool,
        'skip_density': bool,
        'skip_bedrock': bool,
    },
    'islands': {
        'connectivity': int,
        'min_size': int,
        'buffer': float,
        'simplify': float,
        'no_holes': bool,
        'layout': str,
        'canonical_triangulation': bool,
        'basic': bool,
    },
    'xml': {
        'visualize': bool,
        'category_plots': bool,
        'no_summary': bool,
        'no_json': bool,
    },
    'run': {
        'no_layout': bool,
        'no_islands': bool,
        'no_xml': bool,
        'no_matches': bool,
        'island_layout': str,
        'canonical_triangulation': bool,
        'match_history': str,
        'simplify': float,
        'buffer': float,
    },
    'matches': {
        'color_mode': str,
        'map_base': str,
        'match_dir': str,
    },
}

# The ``run`` orchestrator proxies settings from these sections so that
# e.g. ``islands.simplify`` is picked up by ``ctw run`` automatically.
_RUN_MERGE_SECTIONS = ('layout', 'islands')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_config_arg() -> str | None:
    """Extract ``--config`` value from sys.argv without full argparse parsing."""
    for i, arg in enumerate(sys.argv):
        if arg == '--config' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith('--config='):
            return arg.split('=', 1)[1]
    return None


def load_config(cli_config: str | None = None) -> dict[str, dict]:
    """Discover and load the YAML config file.

    Returns a validated dict of ``{section: {key: value}}`` with all keys
    normalised to underscore form.  Returns ``{}`` when no config is found.
    """
    path = _discover_path(cli_config)
    if path is None:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)
    except Exception as exc:
        print(f"Warning: failed to read config {path}: {exc}")
        return {}
    if not isinstance(raw, dict):
        return {}
    return _validate(raw, path)


def apply_config_to_parsers(
    subparsers: argparse.Action,
    config: dict[str, dict],
) -> None:
    """Set YAML values as parser defaults so CLI args still override them."""
    if not config:
        return

    global_cfg = config.get('global', {})

    for cmd_name, cmd_parser in subparsers.choices.items():
        section = config.get(cmd_name, {})

        # For ``run``, also merge layout/islands sections
        if cmd_name == 'run':
            merged = dict(global_cfg)
            for extra in _RUN_MERGE_SECTIONS:
                merged.update(config.get(extra, {}))
            merged.update(section)
        else:
            merged = {**global_cfg, **section}

        _apply_to_parser(cmd_parser, merged)

        # Recurse into nested subparsers (e.g. matches → trace, index, …)
        _apply_to_nested(cmd_parser, merged)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _discover_path(cli_config: str | None) -> Path | None:
    if cli_config:
        p = Path(cli_config)
        if p.exists():
            return p
        print(f"Warning: config file not found: {p}")
        return None
    cwd_config = Path('ctw_config.yaml')
    if cwd_config.exists():
        return cwd_config
    return None


def _validate(raw: dict, path: Path) -> dict[str, dict]:
    validated: dict[str, dict] = {}
    for section, entries in raw.items():
        if section not in CONFIG_SCHEMA:
            print(f"Warning: unknown config section '{section}' in {path}, ignoring")
            continue
        if not isinstance(entries, dict):
            print(f"Warning: config section '{section}' must be a mapping, ignoring")
            continue
        schema = CONFIG_SCHEMA[section]
        section_out: dict[str, object] = {}
        for key, value in entries.items():
            norm_key = key.replace('-', '_')
            if norm_key not in schema:
                print(f"Warning: unknown key '{key}' in [{section}], ignoring")
                continue
            expected = schema[norm_key]
            if not isinstance(value, expected):
                # Allow int → float promotion
                if expected is float and isinstance(value, int):
                    value = float(value)
                else:
                    print(
                        f"Warning: [{section}].{key} expected {expected.__name__}, "
                        f"got {type(value).__name__}, ignoring"
                    )
                    continue
            section_out[norm_key] = value
        if section_out:
            validated[section] = section_out
    return validated


def _get_parser_dests(parser: argparse.ArgumentParser) -> set[str]:
    """Return the set of known argument ``dest`` names for a parser."""
    return {a.dest for a in parser._actions if a.dest != 'help'}


def _apply_to_parser(parser: argparse.ArgumentParser, merged: dict) -> None:
    known = _get_parser_dests(parser)
    filtered = {k: v for k, v in merged.items() if k in known}
    if filtered:
        parser.set_defaults(**filtered)


def _apply_to_nested(parser: argparse.ArgumentParser, merged: dict) -> None:
    """Apply config defaults to sub-subparsers (one level deep)."""
    if parser._subparsers is None:
        return
    for action in parser._subparsers._group_actions:
        if isinstance(action, argparse._SubParsersAction):
            for _name, sub_parser in action.choices.items():
                _apply_to_parser(sub_parser, merged)
