"""'db' subcommand — run SQL queries against the analysis database."""

import argparse
import re
from pathlib import Path

from ctw.common import ensure_match_db


DEFAULT_QUERY_FILE = Path('scripts/debug_queries.sql')


def register(subparsers):
    db_parser = subparsers.add_parser(
        'db',
        help='Run SQL queries against the analysis database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  ctw db "SELECT ..."                   Run ad-hoc SQL
  ctw db --list                         List available named queries
  ctw db --run 1a                       Run query "1a" from debug_queries.sql
  ctw db --run 1a,2b,5d                 Run multiple named queries
  ctw db --section inventory            Run all queries in a section
  ctw db --all                          Run all queries from the file

Examples:
  ctw db "SELECT COUNT(*) FROM matches"
  ctw db --list
  ctw db --run 5d
  ctw db --run 1a,1c
  ctw db --section "data integrity"
  ctw db --all
  ctw db --file my_queries.sql --run 1a
""",
    )
    db_parser.add_argument('sql', nargs='?', help='Inline SQL query to execute')
    db_parser.add_argument('--list', action='store_true',
                           help='List available named queries')
    db_parser.add_argument('--run', help='Run named query(ies) by ID (e.g. 1a or 1a,2b,5d)')
    db_parser.add_argument('--section',
                           help='Run all queries in a section (case-insensitive match)')
    db_parser.add_argument('--all', action='store_true',
                           help='Run all queries from the file')
    db_parser.add_argument('--file', help=f'SQL file path (default: {DEFAULT_QUERY_FILE})')
    db_parser.set_defaults(func=handler)


def _parse_query_file(path: Path) -> list[dict]:
    """Parse a SQL file with named queries into structured entries.

    Expected format:
        -- =====================
        -- 1. SECTION NAME
        -- =====================
        -- 1a. Query description
        SELECT ...;

    Returns list of dicts: {id, name, section, sql}
    """
    text = path.read_text(encoding='utf-8')
    queries = []
    current_section = ''

    # Match section headers like "-- 1. INVENTORY"
    section_re = re.compile(r'^--\s*\d+\.\s*(.+)$', re.MULTILINE)
    # Match query headers like "-- 1a. All maps with match counts"
    query_re = re.compile(r'^--\s*(\d+[a-z])\.\s*(.+)$', re.MULTILINE)

    # Find all sections and queries with their positions
    sections = [(m.start(), m.group(1).strip()) for m in section_re.finditer(text)]
    query_headers = [(m.start(), m.group(1), m.group(2).strip()) for m in query_re.finditer(text)]

    for i, (pos, qid, name) in enumerate(query_headers):
        # Determine section for this query
        for sec_pos, sec_name in reversed(sections):
            if sec_pos < pos:
                current_section = sec_name
                break

        # Extract SQL between this header and the next header (or EOF)
        header_end = text.index('\n', pos) + 1
        if i + 1 < len(query_headers):
            next_pos = query_headers[i + 1][0]
        else:
            next_pos = len(text)

        sql_block = text[header_end:next_pos].strip()
        # Remove comment-only lines and trailing semicolons for clean execution
        sql_lines = []
        for line in sql_block.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('--'):
                sql_lines.append(line)

        sql = '\n'.join(sql_lines).strip().rstrip(';')
        if sql:
            queries.append({
                'id': qid,
                'name': name,
                'section': current_section,
                'sql': sql,
            })

    return queries


def _run_query(conn, sql: str, label: str = None):
    """Execute a query and print results as a formatted table."""
    if label:
        print(f"\n--- {label} ---")

    try:
        result = conn.execute(sql)
        df = result.fetchdf()
        if len(df) == 0:
            print("(no rows)")
        else:
            print(df.to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")

    print()


def handler(args):
    import duckdb

    ensure_match_db()
    query_file = Path(args.file) if args.file else DEFAULT_QUERY_FILE

    # Mode: list available queries
    if args.list:
        if not query_file.exists():
            print(f"Query file not found: {query_file}")
            return
        queries = _parse_query_file(query_file)
        current_section = ''
        for q in queries:
            if q['section'] != current_section:
                current_section = q['section']
                print(f"\n  {current_section}")
                print(f"  {'-' * len(current_section)}")
            print(f"  {q['id']:>4}  {q['name']}")
        print()
        return

    # Mode: run named query(ies)
    if args.run:
        if not query_file.exists():
            print(f"Query file not found: {query_file}")
            return
        queries = _parse_query_file(query_file)
        query_map = {q['id']: q for q in queries}
        ids = [qid.strip() for qid in args.run.split(',')]

        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        for qid in ids:
            q = query_map.get(qid)
            if q is None:
                print(f"Unknown query ID: {qid}")
                continue
            _run_query(conn, q['sql'], f"{q['id']}. {q['name']}")
        conn.close()
        return

    # Mode: run section
    if args.section:
        if not query_file.exists():
            print(f"Query file not found: {query_file}")
            return
        queries = _parse_query_file(query_file)
        section_lower = args.section.lower()
        matched = [q for q in queries if section_lower in q['section'].lower()]
        if not matched:
            print(f"No queries found for section '{args.section}'")
            print("Available sections:")
            for s in sorted(set(q['section'] for q in queries)):
                print(f"  {s}")
            return

        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        for q in matched:
            _run_query(conn, q['sql'], f"{q['id']}. {q['name']}")
        conn.close()
        return

    # Mode: run all
    if args.all:
        if not query_file.exists():
            print(f"Query file not found: {query_file}")
            return
        queries = _parse_query_file(query_file)
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        for q in queries:
            _run_query(conn, q['sql'], f"{q['id']}. {q['name']}")
        conn.close()
        return

    # Mode: inline SQL
    if args.sql:
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        _run_query(conn, args.sql)
        conn.close()
        return

    # No mode specified — show help
    print("No query specified. Use --help for usage, or --list to see available queries.")
