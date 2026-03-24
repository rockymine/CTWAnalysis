"""Check which stub maps can be found in external map repositories.

For each map in the DB with stub=TRUE, checks whether a folder exists in:
  - CommunityMaps:  C:/Users/Michael/source/repos/CommunityMaps/ctw/
  - PublicMaps:     C:/Users/Michael/source/repos/PublicMaps/ctw/

Prints a summary table grouped by location, then lists maps not found anywhere.
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "match_analysis" / "metadata.db"
COMMUNITY_MAPS = Path("C:/Users/Michael/source/repos/CommunityMaps/ctw")
PUBLIC_MAPS    = Path("C:/Users/Michael/source/repos/PublicMaps/ctw")

con = duckdb.connect(str(DB_PATH), read_only=True)

rows = con.execute("""
    SELECT mp.map_slug, COUNT(mat.match_id) AS match_count
    FROM maps mp
    LEFT JOIN matches mat ON mp.map_id = mat.map_id
    WHERE mp.stub = TRUE
    GROUP BY mp.map_slug
    ORDER BY match_count DESC, mp.map_slug
""").fetchall()

con.close()

in_community: list[tuple[str, int]] = []
in_public:    list[tuple[str, int]] = []
not_found:    list[tuple[str, int]] = []

for slug, match_count in rows:
    if (COMMUNITY_MAPS / slug).is_dir():
        in_community.append((slug, match_count))
    elif (PUBLIC_MAPS / slug).is_dir():
        in_public.append((slug, match_count))
    else:
        not_found.append((slug, match_count))

def print_section(title: str, entries: list[tuple[str, int]]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}  ({len(entries)} maps)")
    print(f"{'=' * 60}")
    if not entries:
        print("  (none)")
        return
    for slug, match_count in entries:
        print(f"  {slug:<45} {match_count:>4} matches")

print_section("Found in CommunityMaps", in_community)
print_section("Found in PublicMaps",    in_public)
print_section("Not found anywhere",     not_found)

total_matches_available = sum(c for _, c in in_community) + sum(c for _, c in in_public)
total_matches_missing   = sum(c for _, c in not_found)
print(f"\nSummary: {len(in_community)} community, {len(in_public)} public, "
      f"{len(not_found)} missing")
print(f"Matches processable: {total_matches_available}, "
      f"blocked (no map folder): {total_matches_missing}")
