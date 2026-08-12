import asyncio
import time
import math
from ..models.enums import RampStrategy


class RateLimiter:
    """Token bucket rate limiter for controlling request throughput.

    Uses a shared asyncio.Lock-protected token bucket to ensure smooth
    request distribution even at high concurrency levels.
    """

    def __init__(self, max_rate: float, burst: int = 10):
        self._max_rate = max_rate  # tokens per second
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def update_rate(self, new_rate: float) -> None:
        self._max_rate = new_rate
        self._burst = max(1, int(new_rate * 0.1))

    async def acquire(self) -> float:
        """Acquire a single token, waiting if necessary.

        Returns the wait time in seconds (for metrics).
        """
        if self._max_rate <= 0:
            return 0.0

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._max_rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0

            # Calculate wait time for next token
            wait = (1.0 - self._tokens) / self._max_rate
            self._tokens = 0.0
            self._last_refill = now + wait

        await asyncio.sleep(wait)
        return wait


class RampController:
    """Manages gradual changes in user count over time."""

    def __init__(
        self,
        strategy: RampStrategy,
        duration_seconds: float,
        start_value: int,
        end_value: int,
    ):
        self._strategy = strategy
        self._duration = duration_seconds
        self._start = start_value
        self._end = end_value
        self._start_time: float | None = None

    def start(self) -> None:
        self._start_time = time.monotonic()

    def current_value(self, elapsed: float | None = None) -> int:
        if self._start_time is None:
            return self._start
        if elapsed is None:
            elapsed = time.monotonic() - self._start_time

        progress = min(1.0, elapsed / self._duration) if self._duration > 0 else 1.0

        if self._strategy == RampStrategy.STEP:
            # Step strategy: jump in 25% increments
            step = math.floor(progress * 4) / 4
            return self._start + int((self._end - self._start) * step)

        # Linear (default)
        if progress >= 1.0:
            return self._end
        return self._start + int((self._end - self._start) * progress)

    @property
    def is_complete(self) -> bool:
        if self._start_time is None:
            return False
        return (time.monotonic() - self._start_time) >= self._duration
