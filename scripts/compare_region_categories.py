"""Compare v1 vs v2 region category assignments across all available maps.

Usage
-----
    python scripts/compare_region_categories.py
    python scripts/compare_region_categories.py --map-dir <path> [--map-dir <path> ...]
    python scripts/compare_region_categories.py --map <slug>          # single map

Reads map.xml files from the configured map directories (or from paths given via
--map-dir).  Parses each map with MapXMLParser, runs both
``identify_region_categories`` (v1) and ``identify_region_categories_v2`` (v2),
diffs the results, and writes a summary to stdout plus a JSON artifact at
``scripts/region_category_comparison.json``.

Exit code 0 = no regressions detected.  Non-zero = at least one map flagged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from xml_analysis.builder import MapXMLParser  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _diff_categories(
    v1: dict[str, list[str]],
    v2: dict[str, list[str]],
) -> list[dict]:
    """Return a list of move records {region_id, from_cat, to_cat}.

    Only regions whose bucket changed are included.
    """
    # Build id → category mapping for each version
    v1_map: dict[str, str] = {rid: cat for cat, ids in v1.items() for rid in ids}
    v2_map: dict[str, str] = {rid: cat for cat, ids in v2.items() for rid in ids}

    all_ids = set(v1_map) | set(v2_map)
    moves: list[dict] = []
    for rid in sorted(all_ids):
        from_cat = v1_map.get(rid, "<absent>")
        to_cat   = v2_map.get(rid, "<absent>")
        if from_cat != to_cat:
            moves.append({"region_id": rid, "from": from_cat, "to": to_cat})
    return moves


def _is_regression(move: dict) -> bool:
    """Heuristic: flag a move as a possible regression for manual review.

    Expected good moves:
    - spawn  → wool   (wool-spawn drop points)
    - spawn  → other  (complement utility regions like not-spawns)
    - <absent> → spawn (team_spawn_ids guard adding a missing spawn)

    Anything else warrants review.
    """
    good_moves = {
        ("spawn",    "wool"),    # wool item-spawner drop points reclassified
        ("spawn",    "other"),   # complement utility regions (not-spawns) removed from Teams
        ("<absent>", "spawn"),   # newly anchored team spawn (wasn't in any category)
        ("other",    "spawn"),   # team spawn with unconventional name rescued from other
        ("build",    "spawn"),   # rare: spawn region with "build" in name
    }
    return (move["from"], move["to"]) not in good_moves


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def compare_map(xml_path: Path) -> dict:
    """Parse one map.xml and return a comparison record."""
    try:
        parser = MapXMLParser(str(xml_path))
        data   = parser.parse()
        v1     = parser.identify_region_categories(data)
        v2     = parser.identify_region_categories_v2(data)
    except Exception as exc:
        return {
            "map": xml_path.parent.name,
            "xml_path": str(xml_path),
            "error": str(exc),
            "moves": [],
            "regressions": [],
        }

    moves       = _diff_categories(v1, v2)
    regressions = [m for m in moves if _is_regression(m)]

    return {
        "map":         xml_path.parent.name,
        "xml_path":    str(xml_path),
        "error":       None,
        "team_spawns": [
            s.region.id for s in data.spawns if s.region and s.region.id
        ],
        "observer_spawn": (
            data.observer_spawn.region.id
            if data.observer_spawn and data.observer_spawn.region else None
        ),
        "v1": v1,
        "v2": v2,
        "moves":       moves,
        "regressions": regressions,
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _find_xml_files(map_dirs: list[Path], single_map: str | None) -> list[Path]:
    xml_files: list[Path] = []
    for map_dir in map_dirs:
        if not map_dir.exists():
            print(f"  [WARN] map-dir not found: {map_dir}", file=sys.stderr)
            continue
        for xml_path in sorted(map_dir.rglob("map.xml")):
            if single_map and xml_path.parent.name != single_map:
                continue
            xml_files.append(xml_path)
    return xml_files


def _default_map_dirs() -> list[Path]:
    """Load map directories from map_viewer/config.json if available."""
    config_path = _REPO_ROOT / "map_viewer" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            dirs: list[Path] = []
            maps_folder = cfg.get("maps_folder", "").strip()
            if maps_folder:
                dirs.append(Path(maps_folder))
            # Also include the built-in map_folders directory
            builtin = _REPO_ROOT / "map_folders"
            if builtin.exists():
                dirs.append(builtin)
            return dirs
        except Exception:
            pass
    return [_REPO_ROOT / "map_folders"]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_summary(results: list[dict]) -> None:
    ok_count         = sum(1 for r in results if not r["error"] and not r["moves"])
    changed_count    = sum(1 for r in results if not r["error"] and r["moves"])
    regression_count = sum(1 for r in results if r["regressions"])
    error_count      = sum(1 for r in results if r["error"])

    print(f"\n{'='*70}")
    print(f"  Region category comparison: v1 -> v2")
    print(f"{'='*70}")
    print(f"  Maps parsed:       {len(results)}")
    print(f"  Unchanged:         {ok_count}")
    print(f"  Changed (good):    {changed_count - regression_count}")
    print(f"  Regressions:       {regression_count}")
    print(f"  Parse errors:      {error_count}")
    print(f"{'='*70}\n")

    # Aggregate move stats
    from collections import Counter
    move_pairs: Counter = Counter()
    for result in results:
        for move in result.get("moves", []):
            move_pairs[(move["from"], move["to"])] += 1

    if move_pairs:
        print("  Move breakdown (from -> to : count):")
        for (from_cat, to_cat), count in sorted(move_pairs.items()):
            flag = ""
            if _is_regression({"from": from_cat, "to": to_cat}):
                flag = "  [REVIEW]"
            print(f"    {from_cat:12s} -> {to_cat:12s} : {count:4d}{flag}")
        print()

    # Per-map detail for changed maps
    for result in results:
        if result["error"]:
            print(f"  [ERROR] {result['map']}: {result['error']}")
            continue
        if not result["moves"]:
            continue

        reg_flag = "  *** REGRESSION ***" if result["regressions"] else ""
        print(f"  {result['map']}{reg_flag}")
        print(f"    team_spawns:    {result.get('team_spawns', [])}")
        print(f"    observer_spawn: {result.get('observer_spawn')}")
        for move in result["moves"]:
            flag = "  [REVIEW]" if _is_regression(move) else ""
            print(f"    {move['region_id']:40s}  {move['from']:12s} -> {move['to']}{flag}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare v1 vs v2 region category assignments across maps."
    )
    parser.add_argument(
        "--map-dir", dest="map_dirs", action="append", type=Path,
        help="Path to a directory containing map sub-folders (repeatable).",
    )
    parser.add_argument(
        "--map", dest="single_map", default=None,
        help="Only compare a single map by slug name.",
    )
    parser.add_argument(
        "--output", default="scripts/region_category_comparison.json",
        help="Path for the JSON artifact (default: scripts/region_category_comparison.json).",
    )
    args = parser.parse_args()

    map_dirs = [Path(d) for d in args.map_dirs] if args.map_dirs else _default_map_dirs()
    xml_files = _find_xml_files(map_dirs, args.single_map)

    if not xml_files:
        print("No map.xml files found. Pass --map-dir to specify locations.", file=sys.stderr)
        return 1

    print(f"Comparing {len(xml_files)} map(s) across {len(map_dirs)} director(y/ies)…")

    results: list[dict] = []
    for xml_path in xml_files:
        result = compare_map(xml_path)
        status = "ERROR" if result["error"] else ("CHANGED" if result["moves"] else "ok")
        reg    = " [REGRESSION]" if result["regressions"] else ""
        print(f"  {status:8s}  {result['map']}{reg}")
        results.append(result)

    _print_summary(results)

    # Write JSON artifact (strip v1/v2 full dicts to keep file manageable — keep moves only)
    artifact_path = _REPO_ROOT / args.output
    artifact: list[dict] = [
        {k: v for k, v in r.items() if k not in ("v1", "v2")}
        for r in results
    ]
    artifact_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"JSON artifact written to: {artifact_path}")

    has_regressions = any(r["regressions"] for r in results)
    return 1 if has_regressions else 0


if __name__ == "__main__":
    sys.exit(main())
