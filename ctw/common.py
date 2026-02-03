"""Shared helpers for CTW CLI commands."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def resolve_map_folder(map_arg: str) -> Path:
    """Resolve a --map argument to a map folder Path.

    Tries the argument as a direct path first, then as a name
    under map_folders/.
    """
    candidate = Path(map_arg)
    if candidate.is_dir():
        return candidate.resolve()
    resolved = PROJECT_ROOT / 'map_folders' / map_arg
    if resolved.is_dir():
        return resolved
    print(f"Error: Map folder not found: {map_arg}", file=sys.stderr)
    print(f"  Tried: {candidate}", file=sys.stderr)
    print(f"  Tried: {resolved}", file=sys.stderr)
    sys.exit(1)


def collect_map_folders(args) -> list:
    """Return list of map folder Paths from --map or --all."""
    if getattr(args, 'all', False):
        mf_dir = PROJECT_ROOT / 'map_folders'
        if not mf_dir.exists():
            print(f"Error: map_folders directory not found", file=sys.stderr)
            sys.exit(1)
        return sorted(f for f in mf_dir.iterdir() if f.is_dir())
    if getattr(args, 'map', None):
        return [resolve_map_folder(args.map)]
    print("Error: Must specify either --map or --all", file=sys.stderr)
    sys.exit(1)


def ensure_match_db():
    """Initialize match DB if it doesn't exist yet."""
    db_path = Path('match_analysis/metadata.db')
    if not db_path.exists():
        from scripts.initialize_analysis_db import initialize_database
        initialize_database()
