"""OpenAPI-based load tester for Java (Spring) services.

Self-contained package: parses an OpenAPI (Swagger) document, generates test
data from the schemas, smoke-tests every endpoint, load-tests them with
``asyncio`` + ``aiohttp`` and ranks them by P95/P99 latency.

Run with ``python -m java --help`` from the repository root.
"""

__version__ = "0.1.0"
