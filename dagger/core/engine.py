import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable

from ..models.config import TestConfig
from ..models.enums import RunStatus, RampStrategy
from ..models.metrics import MetricsSummary, MetricsSnapshot
from .session import TestSession
from .worker import VirtualUser, RequestCounter
from .throttle import RateLimiter, RampController

LOGGER = logging.getLogger("dagger")


class TestEngine:
    """Top-level orchestrator for a stress test run.

    Coordinates: session lifecycle, worker spawning, ramp control,
    rate limiting, metrics collection, and graceful shutdown.
    """

    def __init__(
        self,
        config: TestConfig,
        plugin_manager: Optional[object] = None,
        display_callback: Optional[Callable[[MetricsSnapshot], Awaitable[None]]] = None,
    ):
        self._config = config
        self._plugin_manager = plugin_manager
        self._display_callback = display_callback
        self._session: Optional[TestSession] = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._request_counter = RequestCounter()

        # Computed test end condition
        self._target_duration: float = 0.0
        self._target_requests: int = 0

    async def run(self) -> MetricsSummary:
        """Execute the test and return final metrics summary."""
        self._session = await TestSession.create(self._config)
        self._session.start_time = time.monotonic()
        self._session.status = RunStatus.RUNNING

        # Set up rate limiter if configured
        if self._config.rate_limit > 0:
            self._rate_limiter = RateLimiter(self._config.rate_limit)

        # Determine end condition
        if self._config.total_requests is not None:
            self._target_requests = self._config.total_requests
        if self._config.duration is not None:
            self._target_duration = self._config.duration.total_seconds()

        # Set up ramp controllers
        ramp_up_controller: Optional[RampController] = None
        ramp_down_controller: Optional[RampController] = None

        if self._config.ramp_up is not None:
            ramp_dur = self._config.ramp_up.total_seconds()
            if ramp_dur > 0:
                ramp_up_controller = RampController(
                    strategy=self._config.ramp_strategy,
                    duration_seconds=ramp_dur,
                    start_value=1,
                    end_value=self._config.concurrency,
                )
                ramp_up_controller.start()

        if self._config.ramp_down is not None:
            ramp_dur = self._config.ramp_down.total_seconds()
            if ramp_dur > 0:
                ramp_down_controller = RampController(
                    strategy=self._config.ramp_strategy,
                    duration_seconds=ramp_dur,
                    start_value=self._config.concurrency,
                    end_value=1,
                )

        # Fire plugin on_test_start hook
        if self._plugin_manager:
            await self._plugin_manager.call_hook("on_test_start", self._session)

        # Launch worker tasks
        active_workers: list[asyncio.Task] = []
        current_concurrency = 0
        target_concurrency = 1

        # Result collector task
        collector_task = asyncio.create_task(self._result_collector())

        # Live display update task
        if self._display_callback:
            display_task = asyncio.create_task(self._live_display_loop())
        else:
            display_task = None

        try:
            while not self._session.stop_event.is_set():
                elapsed = time.monotonic() - self._session.start_time

                # Check duration-based end condition
                if self._target_duration > 0 and elapsed >= self._target_duration:
                    LOGGER.info("Target duration reached, stopping...")
                    break

                # Check request-count end condition
                if self._target_requests > 0 and self._request_counter.value >= self._target_requests:
                    LOGGER.info("Target request count reached, stopping...")
                    break

                # Handle ramp-up
                if ramp_up_controller and not ramp_up_controller.is_complete:
                    target_concurrency = ramp_up_controller.current_value(elapsed)
                else:
                    # Handle ramp-down
                    if ramp_down_controller is not None and self._target_duration > 0:
                        ramp_remaining = self._target_duration - elapsed
                        ramp_down_dur = self._config.ramp_down.total_seconds()  # type: ignore[union-attr]
                        if ramp_remaining <= ramp_down_dur:
                            ramp_down_controller.start()
                            target_concurrency = ramp_down_controller.current_value(
                                ramp_down_dur - ramp_remaining
                            )

                    if target_concurrency < self._config.concurrency and (
                        ramp_down_controller is None or not hasattr(ramp_down_controller, '_start_time') or ramp_down_controller._start_time is None
                    ):
                        target_concurrency = self._config.concurrency

                # Simple ramp-down fix
                if ramp_down_controller is not None and self._target_duration > 0:
                    ramp_remaining = self._target_duration - elapsed
                    ramp_down_dur = self._config.ramp_down.total_seconds()  # type: ignore[union-attr]
                    if ramp_remaining <= ramp_down_dur:
                        if ramp_down_controller._start_time is None:
                            ramp_down_controller.start()
                        target_concurrency = max(1, ramp_down_controller.current_value(
                            ramp_down_dur - ramp_remaining
                        ))

                # Adjust worker count
                while current_concurrency < target_concurrency:
                    worker = VirtualUser(
                        user_id=current_concurrency,
                        config=self._config,
                        session=self._session,
                        rate_limiter=self._rate_limiter,
                        request_counter=self._request_counter,
                    )
                    task = asyncio.create_task(worker.run())
                    active_workers.append(task)
                    current_concurrency += 1

                # Sleep briefly between management cycles
                await asyncio.sleep(0.05)

        except Exception as e:
            LOGGER.error("Engine error: %s", e, exc_info=True)
            self._session.status = RunStatus.ERROR
        finally:
            # Initiate graceful shutdown
            self._session.initiate_shutdown()

            # Wait for workers to finish (with timeout)
            if active_workers:
                done, pending = await asyncio.wait(
                    active_workers, timeout=5.0
                )
                for task in pending:
                    task.cancel()

            # Stop collector
            self._session.stop_event.set()
            if collector_task and not collector_task.done():
                collector_task.cancel()

            if display_task and not display_task.done():
                display_task.cancel()
                try:
                    await display_task
                except asyncio.CancelledError:
                    pass

            self._session.end_time = time.monotonic()
            self._session.status = RunStatus.COMPLETED

            # Fire plugin on_test_end hook
            if self._plugin_manager:
                await self._plugin_manager.call_hook(
                    "on_test_end", self._session.metrics.finalize({})
                )

            await self._session.close()

        # Build final summary
        config_summary = {
            "url": self._config.target.url,
            "method": self._config.target.method.value,
            "concurrency": self._config.concurrency,
            "duration": self._target_duration,
            "total_requests": self._target_requests,
            "tags": self._config.tags,
        }
        return self._session.metrics.finalize(config_summary)

    async def _result_collector(self) -> None:
        """Background task: drain result queue and feed metrics collector."""
        while not self._session.stop_event.is_set() or not self._session.result_queue.empty():
            try:
                result = await asyncio.wait_for(
                    self._session.result_queue.get(), timeout=0.1
                )
                self._session.metrics.record(result)

                # Fire plugin post_response hook
                if self._plugin_manager:
                    await self._plugin_manager.call_hook("post_response", result)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _live_display_loop(self) -> None:
        """Background task: periodically update the live display."""
        if not self._display_callback:
            return

        interval = self._config.live_refresh_ms / 1000.0
        while not self._session.stop_event.is_set():
            try:
                snapshot = self._session.metrics.snapshot()
                # Count active workers (cannot track perfectly, but we estimate)
                active = self._request_counter.value - snapshot.total_requests + self._config.concurrency
                snapshot.active_users = max(0, min(self._config.concurrency, self._config.concurrency))

                await self._display_callback(snapshot)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.debug("Display update error: %s", e)
