"""Shared helpers for CTW CLI commands."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / 'output'


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
    """Return list of map folder Paths from --map or --all.

    When --all is used, scans --map-dir (if provided) or the default
    map_folders/ directory.
    """
    if getattr(args, 'all', False):
        map_dir = getattr(args, 'map_dir', None)
        mf_dir = Path(map_dir) if map_dir else PROJECT_ROOT / 'map_folders'
        if not mf_dir.exists():
            print(f"Error: map directory not found: {mf_dir}", file=sys.stderr)
            sys.exit(1)
        return sorted(f for f in mf_dir.iterdir() if f.is_dir())
    if getattr(args, 'map', None):
        names = [n.strip() for n in args.map.split(',') if n.strip()]
        return [resolve_map_folder(n) for n in names]
    print("Error: Must specify either --map or --all", file=sys.stderr)
    sys.exit(1)


def resolve_output_dir(
    map_folder: Path,
    output_root: str = None,
    create: bool = False,
) -> Path:
    """Resolve the per-map output directory.

    Args:
        map_folder: Map input folder (used for slug = folder name).
        output_root: Override output root (default: project_root/output).
        create: If True, create the directory. False for read-only commands.

    Returns:
        Path: output_root / map_folder.name
    """
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    out = root / map_folder.name
    if create:
        out.mkdir(parents=True, exist_ok=True)
    return out


def ensure_match_db():
    """Initialize match DB if it doesn't exist yet."""
    db_path = Path('match_analysis/metadata.db')
    if not db_path.exists():
        from match_analysis.initialize_analysis_db import initialize_database
        initialize_database()
