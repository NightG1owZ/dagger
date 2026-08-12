import asyncio
import logging
import random
import time
from typing import Optional

from ..models.config import TestConfig
from ..models.target import TargetSpec
from ..models.result import RequestResult
from .requestor import RequestBuilder
from .throttle import RateLimiter

LOGGER = logging.getLogger("dagger")


class VirtualUser:
    """Simulates a single concurrent user executing requests in a loop."""

    def __init__(
        self,
        user_id: int,
        config: TestConfig,
        session: "TestSession",
        rate_limiter: Optional[RateLimiter],
        request_counter: "RequestCounter",
    ):
        self._user_id = user_id
        self._config = config
        self._session = session
        self._rate_limiter = rate_limiter
        self._request_counter = request_counter
        self._requestor = RequestBuilder(
            target=config.target,
            session=session.client_session,
            timeout_seconds=config.timeout.total_seconds(),
            connect_timeout_seconds=config.connect_timeout.total_seconds(),
            verify_ssl=config.verify_ssl,
            follow_redirects=config.follow_redirects,
            limit_response_size=config.limit_response_size,
        )
        self._retry_delay = config.retry_delay.total_seconds()
        self._max_retries = config.max_retries

    async def run(self) -> None:
        """Main coroutine loop: request -> record -> repeat until stopped."""
        while not self._session.stop_event.is_set():
            try:
                result = await self._single_request()
                await self._session.result_queue.put(result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.debug("VirtualUser %d unexpected error: %s", self._user_id, e)

    async def _single_request(self) -> RequestResult:
        """Execute one request with optional rate limiting and retries."""
        # Wait for rate limiter token if configured
        if self._rate_limiter:
            await self._rate_limiter.acquire()

        request_index = self._request_counter.next()

        for attempt in range(self._max_retries + 1):
            result = await self._requestor.execute(request_index, self._user_id)

            if result.error is None or attempt >= self._max_retries:
                return result

            # Exponential backoff with jitter
            delay = self._retry_delay * (2 ** attempt) * (0.5 + random.random())
            await asyncio.sleep(delay)

        return result  # unreachable but keeps type checker happy


class RequestCounter:
    """Global request counter (safe in single-threaded asyncio)."""

    def __init__(self):
        self._count = 0

    def next(self) -> int:
        self._count += 1
        return self._count

    @property
    def value(self) -> int:
        return self._count
