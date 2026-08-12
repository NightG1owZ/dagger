"""Auto-refresh Bearer token plugin."""

import logging
import time
from typing import Optional

import aiohttp

from ..base import DaggerPlugin

LOGGER = logging.getLogger("dagger")


class AuthBearerPlugin(DaggerPlugin):
    """Automatically refreshes Bearer tokens during long test runs."""

    name = "auth_bearer"
    version = "0.1.0"
    description = "Auto-refresh Bearer authorization tokens"

    config_schema = {
        "type": "object",
        "properties": {
            "token_endpoint": {"type": "string", "format": "uri"},
            "client_id": {"type": "string"},
            "client_secret": {"type": "string"},
            "refresh_interval": {"type": "string", "default": "300s"},
        },
        "required": ["token_endpoint", "client_id", "client_secret"],
    }

    def __init__(self):
        self._token: Optional[str] = None
        self._token_endpoint: Optional[str] = None
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._refresh_interval: float = 300.0
        self._last_refresh: float = 0.0

    async def on_configure(self, config: dict) -> None:
        self._token_endpoint = config.get("token_endpoint")
        self._client_id = config.get("client_id")
        self._client_secret = config.get("client_secret")

        interval_str = config.get("refresh_interval", "300s")
        from ...utils.misc import parse_duration
        self._refresh_interval = parse_duration(interval_str)

    async def pre_request(self, target: "TargetSpec") -> "TargetSpec":
        if not self._token or (time.monotonic() - self._last_refresh > self._refresh_interval):
            await self._refresh_token()

        if self._token:
            target.headers["Authorization"] = f"Bearer {self._token}"
        return target

    async def _refresh_token(self) -> None:
        if not self._token_endpoint:
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._token_endpoint,
                    json={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "client_credentials",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._token = data.get("access_token")
                        self._last_refresh = time.monotonic()
                        LOGGER.info("Bearer token refreshed successfully")
                    else:
                        LOGGER.error("Token refresh failed: HTTP %s", resp.status)
        except Exception as e:
            LOGGER.error("Token refresh error: %s", e)
