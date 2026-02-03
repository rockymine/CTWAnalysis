"""'docs' subcommand — generate API documentation."""

import subprocess
import sys

from ctw.common import PROJECT_ROOT


def register(subparsers):
    p = subparsers.add_parser('docs', help='Generate API documentation')
    p.set_defaults(func=handler)


def handler(args):
    overview_path = PROJECT_ROOT / 'overview.py'
    if not overview_path.exists():
        print("Error: overview.py not found", file=sys.stderr)
        sys.exit(1)
    subprocess.run([sys.executable, str(overview_path)], cwd=str(PROJECT_ROOT))
