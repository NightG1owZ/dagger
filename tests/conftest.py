"""Shared fixtures for PerfScanner tests."""

from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import pytest_asyncio
from aiohttp import web

SLOW_PATH = "/api/slow"
FAST_PATH = "/api/fast"
SLOW_DELAY = 0.05
FAST_DELAY = 0.001


# --- Threaded server (sync, usable across event loops) -----------------------
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self) -> None:
        time.sleep(SLOW_DELAY if SLOW_PATH in self.path else FAST_DELAY)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_GET  # noqa: N815

    def log_message(self, *args) -> None:  # noqa: ANN002, ANN003
        pass


@pytest.fixture()
def local_server():
    """A real threaded HTTP server; the slow path has a larger fixed delay."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


# --- In-process aiohttp server (deterministic latency, async tests) ----------
async def _slow_handler(request: web.Request) -> web.Response:
    await asyncio.sleep(SLOW_DELAY)
    return web.json_response({"ok": True})


async def _fast_handler(request: web.Request) -> web.Response:
    await asyncio.sleep(FAST_DELAY)
    return web.json_response({"ok": True})


@pytest_asyncio.fixture
async def async_server():
    """An in-process aiohttp.web server with deterministic per-route latency."""
    app = web.Application()
    app.router.add_get(SLOW_PATH, _slow_handler)
    app.router.add_get(FAST_PATH, _fast_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = site._server.sockets[0].getsockname()[:2]  # noqa: SLF001
    yield f"http://{host}:{port}"
    await runner.cleanup()


@pytest.fixture()
def sample_java_project(tmp_path):
    """A minimal Spring-Boot-style project for scanning."""
    controller = tmp_path / "src" / "main" / "java" / "com" / "example"
    controller.mkdir(parents=True)

    (controller / "UserController.java").write_text(
        """\
package com.example;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping("/{id}")
    public String getUser(@PathVariable("id") Long id) { return "ok"; }

    @PostMapping
    public void create(@RequestBody User user) {}

    @RequestMapping(value = "/search", method = RequestMethod.GET)
    public String search() { return "ok"; }

    @DeleteMapping({"/{id}/a", "/{id}/b"})
    public void remove(@PathVariable Long id) {}
}
""",
        encoding="utf-8",
    )

    (controller / "NotAController.java").write_text(
        """\
package com.example;

public class NotAController {
    @GetMapping("/should-not-scan")
    public String nope() { return "nope"; }
}
""",
        encoding="utf-8",
    )

    return tmp_path
