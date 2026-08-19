"""Shared fixtures for the java (OpenAPI load tester) tests."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from aiohttp import web


def build_spec(base_url: str) -> dict:
    """A small OpenAPI 3.0 document exercising most parser features."""
    return {
        "openapi": "3.0.1",
        "info": {"title": "demo", "version": "1.0"},
        "servers": [{"url": base_url}],
        "paths": {
            "/api/fast": {
                "get": {"operationId": "fast", "responses": {"200": {"description": "ok"}}}
            },
            "/api/slow": {
                "get": {"operationId": "slow", "responses": {"200": {"description": "ok"}}}
            },
            "/api/bad": {
                "get": {"operationId": "bad", "responses": {"400": {"description": "bad"}}}
            },
            "/api/boom": {
                "get": {"operationId": "boom", "responses": {"500": {"description": "boom"}}}
            },
            "/api/biz": {
                "get": {"operationId": "biz", "responses": {"200": {"description": "ok"}}}
            },
            "/api/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                        },
                        {
                            "name": "verbose",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean"},
                        },
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/api/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        },
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "minLength": 2, "maxLength": 10},
                        "age": {"type": "integer", "minimum": 0, "maximum": 150},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                }
            }
        },
    }


def make_app(base_url: str) -> web.Application:
    app = web.Application()

    async def handler_spec(request: web.Request) -> web.Response:
        return web.json_response(build_spec(base_url))

    async def handler_ok(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def handler_slow(request: web.Request) -> web.Response:
        await asyncio.sleep(0.05)
        return web.json_response({"ok": True})

    async def handler_bad(request: web.Request) -> web.Response:
        return web.json_response({"msg": "bad request"}, status=400)

    async def handler_boom(request: web.Request) -> web.Response:
        return web.json_response({"msg": "internal"}, status=500)

    async def handler_biz(request: web.Request) -> web.Response:
        return web.json_response({"code": 500, "msg": "business fail"})

    async def handler_code0(request: web.Request) -> web.Response:
        return web.json_response({"code": 0, "ok": True})

    async def handler_echo(request: web.Request) -> web.Response:
        return web.json_response({"method": request.method, "path": request.path})

    async def handler_sleep(request: web.Request) -> web.Response:
        await asyncio.sleep(0.5)
        return web.json_response({"ok": True})

    app.router.add_get("/api/v3/api-docs", handler_spec)
    app.router.add_get("/api/fast", handler_ok)
    app.router.add_get("/api/slow", handler_slow)
    app.router.add_get("/api/bad", handler_bad)
    app.router.add_get("/api/boom", handler_boom)
    app.router.add_get("/api/biz", handler_biz)
    app.router.add_get("/api/code0", handler_code0)
    app.router.add_get("/api/users/{id}", handler_echo)
    app.router.add_post("/api/users", handler_echo)
    app.router.add_get("/api/sleep", handler_sleep)
    return app


@pytest_asyncio.fixture
async def openapi_server():
    """In-process aiohttp server serving the demo spec plus live endpoints."""
    runner = web.AppRunner(make_app(""))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = site._server.sockets[0].getsockname()[:2]  # noqa: SLF001
    base = f"http://{host}:{port}"
    try:
        yield {"base": base, "spec_url": base + "/api/v3/api-docs", "spec": build_spec(base)}
    finally:
        await runner.cleanup()


# --- Threaded server (sync) for CLI tests ------------------------------------
# Sync tests that call ``asyncio.run`` internally must not share the async
# fixture's event loop, so the CLI tests use a plain threaded HTTP server.


class _ThreadedHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    spec: dict = {}

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self) -> None:
        # Drain the request body so keep-alive state never corrupts the stream.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        path = urlparse(self.path).path
        method = self.command
        if path == "/api/v3/api-docs" and method == "GET":
            self._send(200, json.dumps(self.spec).encode("utf-8"))
        elif path == "/api/fast" and method == "GET":
            self._send(200, b'{"ok": true}')
        elif path == "/api/slow" and method == "GET":
            time.sleep(0.05)
            self._send(200, b'{"ok": true}')
        elif path == "/api/bad" and method == "GET":
            self._send(400, b'{"msg": "bad request"}')
        elif path == "/api/boom" and method == "GET":
            self._send(500, b'{"msg": "internal"}')
        elif path == "/api/biz" and method == "GET":
            self._send(200, b'{"code": 500, "msg": "business fail"}')
        elif path == "/api/code0" and method == "GET":
            self._send(200, b'{"code": 0, "ok": true}')
        elif path == "/api/users" and method == "POST":
            self._send(200, b'{"ok": true}')
        elif path.startswith("/api/users/") and method == "GET":
            self._send(200, b'{"ok": true}')
        elif path == "/api/sleep" and method == "GET":
            time.sleep(0.5)
            self._send(200, b'{"ok": true}')
        else:
            self._send(404, b'{"msg": "not found"}')

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, *args) -> None:  # noqa: ANN002, ANN003
        pass


@pytest.fixture
def openapi_http_server():
    """Threaded HTTP server (works from sync CLI tests) serving spec + routes."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ThreadedHandler)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    _ThreadedHandler.spec = build_spec(base)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"base": base, "spec_url": base + "/api/v3/api-docs", "spec": build_spec(base)}
    finally:
        server.shutdown()
        server.server_close()
