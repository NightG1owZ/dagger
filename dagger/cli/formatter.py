"""Custom argparse HelpFormatter with grouped, colored output."""

import argparse
import re


class DaggerHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom formatter that adds spacing between argument groups.

    When used with rich for rendering, the _group_headers tracked
    here allow the caller to insert section breaks and color markup.
    """

    def __init__(self, prog: str, indent_increment: int = 2,
                 max_help_position: int = 32, width: int | None = None):
        super().__init__(prog, indent_increment, max_help_position, width)
        self._current_group: str | None = None
        self._groups: list[dict] = []  # List of {title, description, actions}

    def add_argument(self, action: argparse.Action) -> None:
        if self._current_group is not None:
            # Add to current logical group
            if not hasattr(action, '_dagger_group'):
                action._dagger_group = self._current_group  # type: ignore[attr-defined]
        super().add_argument(action)

    def _format_usage(self, usage, actions, groups, prefix):
        return super()._format_usage(usage, actions, groups, prefix)
