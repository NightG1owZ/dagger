"""Abstract base class for Dagger plugins."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class DaggerPlugin(ABC):
    """Base class for all Dagger plugins.

    Plugins inherit from this class and override hook methods
    to inject custom behavior into the test lifecycle.

    Plugins are discovered via setuptools entry_points under
    the 'dagger.plugins' group.
    """

    name: str = "base"
    version: str = "0.1.0"
    description: str = "Base plugin"
    config_schema: dict = {}

    async def on_configure(self, config: dict) -> None:
        """Called when plugin configuration is loaded."""
        pass

    async def pre_request(self, target: "TargetSpec") -> "TargetSpec":
        """Modify request before it is sent.

        Args:
            target: The TargetSpec about to be executed.

        Returns:
            Modified TargetSpec (or the original if no changes).
        """
        return target

    async def post_response(self, result: "RequestResult") -> "RequestResult":
        """Process a completed request result.

        Args:
            result: The RequestResult from the completed request.

        Returns:
            Modified RequestResult (or the original if no changes).
        """
        return result

    async def on_error(self, result: "RequestResult", exception: Exception) -> None:
        """Called when a request encounters an error."""
        pass

    async def on_test_start(self, session: "TestSession") -> None:
        """Called when a test run begins."""
        pass

    async def on_test_end(self, summary: "MetricsSummary") -> None:
        """Called when a test run completes."""
        pass

    async def on_metric_tick(self, snapshot: "MetricsSnapshot") -> None:
        """Called periodically with live metrics."""
        pass
