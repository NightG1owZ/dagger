import asyncio
import logging
import time
from typing import Optional

import aiohttp

from ..models.config import TestConfig
from ..models.enums import RunStatus
from ..models.metrics import MetricsCollector

LOGGER = logging.getLogger("dagger")


class TestSession:
    """Owns the mutable state for a single test run."""

    def __init__(self, config: TestConfig):
        self.config = config
        self.status = RunStatus.INIT
        self.start_time: float = 0.0
        self.end_time: Optional[float] = None
        self.metrics = MetricsCollector()
        self.client_session: Optional[aiohttp.ClientSession] = None
        self.stop_event = asyncio.Event()
        self.result_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._shutdown_initiated = False

    @classmethod
    async def create(cls, config: TestConfig) -> "TestSession":
        """Factory: create session with configured aiohttp connector."""
        session = cls(config)

        connector = aiohttp.TCPConnector(
            limit=0,  # Unlimited connections
            force_close=not config.keep_alive,
            enable_cleanup_closed=True,
            ttl_dns_cache=300,
        )

        timeout = aiohttp.ClientTimeout(
            total=config.timeout.total_seconds(),
            connect=config.connect_timeout.total_seconds(),
        )

        session.client_session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        )

        return session

    async def close(self) -> None:
        """Clean up resources."""
        if self.client_session and not self.client_session.closed:
            await self.client_session.close()

    def initiate_shutdown(self) -> None:
        """Signal workers to stop (graceful)."""
        if not self._shutdown_initiated:
            self._shutdown_initiated = True
            self.stop_event.set()
            LOGGER.info("Shutdown initiated, draining inflight requests...")

    def force_shutdown(self) -> None:
        """Immediate abort."""
        self.status = RunStatus.ABORTED
        self.stop_event.set()
        if self.end_time is None:
            self.end_time = time.monotonic()
