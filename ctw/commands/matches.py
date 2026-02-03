"""'matches' subcommand — match data analysis commands."""

import argparse
from pathlib import Path

from ctw.common import ensure_match_db


def register(subparsers):
    matches_parser = subparsers.add_parser(
        'matches',
        help='Match data analysis commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  index        Index all match parquet files into the database
  process      Process a specific match by ID
  process-all  Process all unprocessed matches
  list         List matches in the database
  stats        Show database statistics

Examples:
  python ctw.py matches index
  python ctw.py matches list
  python ctw.py matches process 57
  python ctw.py matches process-all
  python ctw.py matches stats
""",
    )
    matches_sub = matches_parser.add_subparsers(
        dest='matches_action', metavar='<action>',
    )

    # matches index
    p = matches_sub.add_parser('index', help='Index all match files')
    p.add_argument('--match-dir', help='Directory containing match parquet files (default: match_logs)')
    p.set_defaults(func=handle_index)

    # matches process
    p = matches_sub.add_parser('process', help='Process a specific match by ID')
    p.add_argument('match_id', type=int, help='Match ID to process')
    p.set_defaults(func=handle_process)

    # matches process-all
    p = matches_sub.add_parser('process-all', help='Process all unprocessed matches')
    p.add_argument('--map-name', help='Only process matches for this map')
    p.set_defaults(func=handle_process_all)

    # matches list
    p = matches_sub.add_parser('list', help='List matches in the database')
    p.add_argument('--map-name', help='Filter by map name')
    p.add_argument('--processed', action='store_true', help='Show only processed matches')
    p.add_argument('--unprocessed', action='store_true', help='Show only unprocessed matches')
    p.set_defaults(func=handle_list)

    # matches stats
    p = matches_sub.add_parser('stats', help='Show database statistics')
    p.set_defaults(func=handle_stats)


def handle_index(args):
    ensure_match_db()
    from match_analysis.match_indexer import index_match_files

    match_dir = args.match_dir or 'match_logs'
    indexed, skipped = index_match_files(match_dir)

    import duckdb
    conn = duckdb.connect('match_analysis/metadata.db')
    result = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT map_name) as maps FROM matches"
    ).fetchone()
    conn.close()

    print(f"\nTotal indexed: {result[0]} matches across {result[1]} maps")


def handle_process(args):
    ensure_match_db()
    from match_analysis.trajectory_extractor import process_match
    process_match(args.match_id)


def handle_process_all(args):
    ensure_match_db()
    import duckdb
    from match_analysis.trajectory_extractor import process_match

    conn = duckdb.connect('match_analysis/metadata.db')

    query = "SELECT match_id FROM matches WHERE processed = FALSE"
    params = []
    if args.map_name:
        query += " AND map_name = ?"
        params.append(args.map_name)
    query += " ORDER BY match_id"

    results = conn.execute(query, params).fetchall()
    conn.close()

    total = len(results)
    if total == 0:
        print("No unprocessed matches found.")
        return

    print(f"Processing {total} matches...")

    for i, (match_id,) in enumerate(results, 1):
        print(f"\n[{i}/{total}] Processing match {match_id}")
        process_match(match_id)


def handle_list(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    query = "SELECT match_id, map_name, player_count, match_duration, processed FROM matches"
    conditions = []
    params = []

    if args.map_name:
        conditions.append("map_name = ?")
        params.append(args.map_name)
    if args.processed:
        conditions.append("processed = TRUE")
    elif args.unprocessed:
        conditions.append("processed = FALSE")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY match_id"

    results = conn.execute(query, params).fetchall()
    conn.close()

    print(f"\nFound {len(results)} matches:\n")
    print(f"{'ID':<6} {'Map':<15} {'Players':<8} {'Duration':<10} {'Processed'}")
    print("-" * 55)

    for match_id, map_name, players, duration, proc in results:
        duration_str = f"{duration:.0f}s" if duration else "N/A"
        proc_str = "yes" if proc else "no"
        print(f"{match_id:<6} {map_name:<15} {players:<8} {duration_str:<10} {proc_str}")


def handle_stats(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    result = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
            COUNT(DISTINCT map_name) as maps,
            SUM(player_count) as total_players,
            SUM(position_count) as total_positions
        FROM matches
    """).fetchone()

    total = result[0]
    if total == 0:
        print("No matches in database. Run 'ctw matches index' first.")
        conn.close()
        return

    print("\n=== Match Database Statistics ===\n")
    print(f"Total matches: {total}")
    print(f"Processed: {result[1]} ({result[1]/total*100:.1f}%)")
    print(f"Unique maps: {result[2]}")
    print(f"Total player records: {result[3]:,}")
    print(f"Total position records: {result[4]:,}")

    print("\n=== Matches by Map ===\n")
    results = conn.execute("""
        SELECT
            map_name,
            COUNT(*) as count,
            SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed
        FROM matches
        GROUP BY map_name
        ORDER BY count DESC
    """).fetchall()

    for map_name, count, processed in results:
        print(f"{map_name:<20} {count:>3} matches ({processed} processed)")

    conn.close()
