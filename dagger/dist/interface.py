"""Distributed testing interface stubs for future expansion."""

from abc import ABC, abstractmethod
from typing import Any


class DistributedCoordinator(ABC):
    """Abstract interface for distributed test coordination.

    This is a placeholder for future distributed testing support.
    The current implementation passes through to local TestEngine.
    """

    @abstractmethod
    async def register_worker(self, worker_info: dict) -> str:
        """Register a worker node, returning its ID."""
        ...

    @abstractmethod
    async def dispatch_plan(self, test_config: dict) -> None:
        """Dispatch a test plan to all registered workers."""
        ...

    @abstractmethod
    async def collect_results(self, worker_id: str) -> list:
        """Collect results from a specific worker."""
        ...

    @abstractmethod
    async def aggregate_metrics(self) -> dict:
        """Aggregate metrics from all workers into a single summary."""
        ...


class LocalCoordinator(DistributedCoordinator):
    """Single-machine pass-through coordinator."""

    async def register_worker(self, worker_info: dict) -> str:
        return "local"

    async def dispatch_plan(self, test_config: dict) -> None:
        pass

    async def collect_results(self, worker_id: str) -> list:
        return []

    async def aggregate_metrics(self) -> dict:
        return {}


class RemoteCoordinatorStub(DistributedCoordinator):
    """Stub that indicates distributed testing is not yet available."""

    async def register_worker(self, worker_info: dict) -> str:
        _ = worker_info
        raise NotImplementedError(
            "Distributed testing is planned for v0.2.0. "
            "Use the local coordinator or run multiple independent dagger instances."
        )

    async def dispatch_plan(self, test_config: dict) -> None:
        _ = test_config
        raise NotImplementedError("Distributed testing is planned for v0.2.0.")

    async def collect_results(self, worker_id: str) -> list:
        _ = worker_id
        raise NotImplementedError("Distributed testing is planned for v0.2.0.")

    async def aggregate_metrics(self) -> dict:
        raise NotImplementedError("Distributed testing is planned for v0.2.0.")
