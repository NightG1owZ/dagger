import logging
import sys
from typing import Optional


def setup_logging(verbosity: int = 0, quiet: bool = False) -> None:
    """Configure logging for the dagger package.

    Args:
        verbosity: Stackable verbosity level (0=WARNING, 1=INFO, 2=DEBUG).
        quiet: Suppress all non-error output.
    """
    logger = logging.getLogger("dagger")

    if quiet:
        logger.setLevel(logging.ERROR)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        return

    levels = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    level = levels.get(verbosity, logging.DEBUG)
    logger.setLevel(level)

    try:
        from rich.logging import RichHandler
        handler = RichHandler(rich_tracebacks=True, show_time=False, show_path=False)
    except ImportError:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    logger.addHandler(handler)
    logger.propagate = False
