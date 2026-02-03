#!/usr/bin/env python3
"""CTW Analysis Toolkit — thin wrapper.

Delegates to ctw.cli.main() so that ``python ctw.py ...`` keeps working.
"""

import importlib
import sys
from pathlib import Path

def main():
    # When run as ``python ctw.py``, this file becomes the ``ctw`` module
    # in sys.modules and shadows the ctw/ package.  Remove it so the
    # package can be imported normally.
    project_root = str(Path(__file__).parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Drop the script-level 'ctw' module so the package is importable.
    sys.modules.pop('ctw', None)
    sys.modules.pop('__mp_main__', None)

    cli = importlib.import_module('ctw.cli')
    cli.main()

if __name__ == '__main__':
    main()
