"""Logging setup for the CTW analysis pipeline.

Two handlers are attached to the 'ctw' logger:

  Console (StreamHandler, INFO)  — one-line summaries per step, warnings
  File    (FileHandler,  DEBUG)  — full detail written to pipeline.log

Usage:
    # Once at process startup (ctw/cli.py):
    from ctw.log import setup_console_logging
    setup_console_logging()

    # Once per map, before running any pipeline steps:
    from ctw.log import setup_map_file_logging
    setup_map_file_logging(map_output_dir)
"""

import logging
from pathlib import Path

_LOGGER = 'ctw'
_CONSOLE_FMT = '%(message)s'
_FILE_FMT = '%(asctime)s  %(levelname)-5s  %(filename)s: %(message)s'
_DATE_FMT = '%H:%M:%S'


def setup_console_logging() -> None:
    """Attach an INFO-level console handler to the 'ctw' logger.

    Idempotent — safe to call multiple times; adds the handler only once.
    """
    logger = logging.getLogger(_LOGGER)
    # Already configured
    if any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    ):
        return
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
    logger.addHandler(ch)


def setup_map_file_logging(map_output_dir: Path) -> None:
    """Attach a DEBUG-level FileHandler for this map run.

    Replaces any previous FileHandler. Writes to
    <map_output_dir>/pipeline.log (overwritten each run).
    """
    logger = logging.getLogger(_LOGGER)

    # Remove previous file handler (sequential map runs)
    for h in logger.handlers[:]:
        if isinstance(h, logging.FileHandler):
            h.close()
            logger.removeHandler(h)

    log_path = map_output_dir / 'pipeline.log'
    fh = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    logger.addHandler(fh)
