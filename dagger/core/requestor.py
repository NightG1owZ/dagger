import time
import logging
import ssl
from typing import Optional

import aiohttp

from ..models.target import TargetSpec
from ..models.result import RequestResult
from ..models.enums import HttpMethod

LOGGER = logging.getLogger("dagger")


class RequestBuilder:
    """Constructs and executes aiohttp requests from a TargetSpec."""

    def __init__(
        self,
        target: TargetSpec,
        session: aiohttp.ClientSession,
        timeout_seconds: float = 30.0,
        connect_timeout_seconds: float = 10.0,
        verify_ssl: bool = True,
        follow_redirects: bool = False,
        limit_response_size: int = 1_048_576,
    ):
        self._target = target
        self._session = session
        self._timeout = aiohttp.ClientTimeout(
            total=timeout_seconds,
            connect=connect_timeout_seconds,
        )
        self._verify_ssl = verify_ssl
        self._follow_redirects = follow_redirects
        self._limit_response_size = limit_response_size

    async def execute(self, request_index: int, virtual_user_id: int) -> RequestResult:
        """Execute the HTTP request and return a RequestResult."""
        start_time = time.monotonic()
        connect_time = 0.0
        ttfb = 0.0
        status_code: Optional[int] = None
        response_size = 0
        error: Optional[str] = None
        error_detail: Optional[str] = None

        url = self._target.url
        method = self._target.method.value
        headers = dict(self._target.headers) if self._target.headers else {}
        cookies = self._target.cookies

        # Build body/kwargs
        kwargs: dict = {"headers": headers, "timeout": self._timeout}
        if cookies:
            kwargs["cookies"] = cookies

        if not self._verify_ssl:
            kwargs["ssl"] = False

        kwargs["allow_redirects"] = self._follow_redirects

        try:
            body: Optional[bytes] = None

            if self._target.json_body is not None:
                kwargs["json"] = self._target.json_body
            elif self._target.form_fields is not None:
                kwargs["data"] = self._target.form_fields
            elif self._target.files is not None:
                form_data = aiohttp.FormData()
                for field_name, file_path in self._target.files:
                    form_data.add_field(field_name, open(file_path, "rb"))
                kwargs["data"] = form_data
            elif self._target.body is not None:
                body = self._target.body
                kwargs["data"] = body

            connect_start = time.monotonic()
            async with self._session.request(method, url, **kwargs) as response:
                connect_time = time.monotonic() - connect_start
                ttfb = connect_time  # approximate; trace_config gives more precision

                status_code = response.status

                # Read response body (limited)
                body_data = await response.content.read(self._limit_response_size)
                response_size = len(body_data)

        except aiohttp.ClientConnectorError as e:
            error = "ConnectionError"
            error_detail = str(e)
        except aiohttp.ServerTimeoutError as e:
            error = "Timeout"
            error_detail = str(e)
        except aiohttp.ClientError as e:
            error = type(e).__name__
            error_detail = str(e)
        except Exception as e:
            error = type(e).__name__
            error_detail = str(e)
        finally:
            # Clean up any opened file handles
            if self._target.files:
                for _, file_path in self._target.files:
                    pass  # file handles managed by FormData context

        latency = time.monotonic() - start_time

        return RequestResult(
            timestamp=start_time,
            latency=latency,
            connect_time=connect_time,
            ttfb=ttfb,
            status_code=status_code,
            response_size=response_size,
            error=error,
            error_detail=error_detail,
            virtual_user_id=virtual_user_id,
            request_index=request_index,
        )
