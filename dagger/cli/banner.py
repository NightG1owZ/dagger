"""SQLMap-style startup banner."""

import random
from rich.console import Console
from rich.text import Text
from .. import __version__


BANNER = r"""
     ____
    / __ \____ _____  ___  _____
   / / / / __ `/ __ \/ _ \/ ___/
  / /_/ / /_/ / /_/ /  __/ /
 /_____/\__,_/ .___/\___/_/
            /_/
"""

TIPS = [
    "Use -c to set the number of concurrent virtual users.",
    "Combine --ramp-up with --ramp-down to simulate realistic traffic patterns.",
    "Export HTML reports with -f html for shareable result charts.",
    "Run 'dagger config' for an interactive setup wizard.",
    "Load saved configs with --config-file to reproduce tests exactly.",
    "Use -H to add custom headers; repeat the flag for multiple headers.",
    "The --rate flag caps requests per second across all virtual users.",
    "Press Ctrl+C once for graceful shutdown, twice for immediate abort.",
    "Use --json to send JSON request bodies; Content-Type is set automatically.",
    "Combine -f text,json,html to get all report formats at once.",
    "Use --save-responses to dump response bodies for debugging.",
    "Set --limit-response-size to control memory usage on large payloads.",
]


def show_banner(console: Console | None = None) -> None:
    """Print the Dagger ASCII banner with version and a random tip."""
    if console is None:
        console = Console()

    banner_text = Text()
    banner_text.append(BANNER, style="bold cyan")
    banner_text.append(f"\n    HTTP Stress Testing Tool v{__version__}", style="dim")
    banner_text.append(f"\n    Tip: {random.choice(TIPS)}\n", style="italic dim")

    console.print(banner_text)
