import asyncio
import logging
import signal
from typing import Callable, Awaitable

LOGGER = logging.getLogger("dagger")


class SignalHandler:
    """Handle OS signals for graceful shutdown.

    First SIGINT/SIGTERM: graceful shutdown (drain inflight requests).
    Second SIGINT/SIGTERM: immediate abort.
    """

    def __init__(self):
        self._shutdown_requested = False
        self._force_abort = False
        self._on_shutdown: Callable[[], Awaitable[None]] | None = None
        self._on_force_abort: Callable[[], Awaitable[None]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def register(
        self,
        on_shutdown: Callable[[], Awaitable[None]],
        on_force_abort: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._on_shutdown = on_shutdown
        self._on_force_abort = on_force_abort
        self._loop = asyncio.get_running_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._loop.add_signal_handler(sig, self._handle_signal, sig)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler for SIGTERM
                if sig == signal.SIGINT:
                    signal.signal(sig, self._sync_handler)

    def _sync_handler(self, signum: int, frame: object) -> None:
        """Fallback sync handler for platforms without add_signal_handler."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._handle_signal, signum)

    def _handle_signal(self, sig: int) -> None:
        sig_name = signal.Signals(sig).name
        if self._force_abort:
            LOGGER.warning("Second %s received, forcing exit", sig_name)
            return

        if self._shutdown_requested:
            LOGGER.warning("Second %s received, forcing immediate abort", sig_name)
            self._force_abort = True
            if self._on_force_abort:
                asyncio.ensure_future(self._on_force_abort())
        else:
            LOGGER.info("%s received, initiating graceful shutdown...", sig_name)
            self._shutdown_requested = True
            if self._on_shutdown:
                asyncio.ensure_future(self._on_shutdown())

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def force_abort(self) -> bool:
        return self._force_abort
