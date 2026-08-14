"""Argument parser tree builder — sqlmap-style CLI interface."""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..models.enums import HttpMethod, RampStrategy, ReportFormat
from ..models.config import TestConfig
from ..models.target import TargetSpec
from ..utils.misc import resolve_url, parse_duration
from .validators import (
    validate_url,
    validate_duration,
    validate_concurrency,
    validate_positive_int,
    validate_rate,
    validate_report_format,
    validate_header,
    validate_file_exists,
)


def build_root_parser() -> argparse.ArgumentParser:
    """Build the complete CLI argument parser tree."""

    parser = argparse.ArgumentParser(
        prog="dagger",
        description="HTTP API Stress Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  dagger run -u https://api.example.com/health -c 50 -d 60s\n"
               "  dagger run -u https://api.example.com/api -X POST --json '{\"key\":\"val\"}' -c 10 -d 30s\n"
               "  dagger run -u https://api.example.com/api -c 100 -d 5m --ramp-up 30s -f html -o ./results\n"
               "  dagger scan ./spring-boot-project --base-url http://localhost:8101/api\n"
               "  dagger config\n"
               "  dagger plugins list",
    )

    # Global flags
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Increase verbosity (-v, -vv, -vvv)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument(
        "--config-file", type=Path, metavar="PATH",
        help="Path to YAML/TOML config file",
    )
    parser.add_argument(
        "--plugin-dir", type=Path, metavar="PATH", action="append", default=[],
        help="Additional plugin search path (repeatable)",
    )

    subparsers = parser.add_subparsers(dest="subcommand", title="Subcommands")

    # ---- dagger run ----
    run_parser = subparsers.add_parser(
        "run",
        help="Run a stress test",
        description="Execute an HTTP stress test against a target URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Target group
    target_group = run_parser.add_argument_group("Target")
    target_group.add_argument(
        "-u", "--url", type=validate_url, metavar="URL",
        help="Target URL (e.g., https://api.example.com/endpoint)",
    )
    target_group.add_argument(
        "-X", "--method", type=HttpMethod, default=HttpMethod.GET,
        choices=list(HttpMethod), metavar="METHOD",
        help="HTTP method (default: GET)",
    )

    # Request group
    req_group = run_parser.add_argument_group("Request")
    req_group.add_argument(
        "-H", "--header", type=validate_header, action="append", metavar='"Key: Value"',
        help="Add request header (repeatable)",
        dest="headers_raw",
    )
    req_group.add_argument(
        "--data", type=str, metavar="STRING", default=None,
        help="Request body (raw string)",
    )
    req_group.add_argument(
        "--json", type=str, metavar="JSON_STRING", default=None,
        help="JSON request body (auto-sets Content-Type: application/json)",
        dest="json_body_raw",
    )
    req_group.add_argument(
        "--form", type=str, action="append", metavar="KEY=VALUE",
        help="Form-encoded body field (repeatable)",
        dest="form_fields_raw",
    )
    req_group.add_argument(
        "-b", "--cookie", type=str, action="append", metavar='"key=value"',
        help="Cookie (repeatable)",
        dest="cookies_raw",
    )
    req_group.add_argument(
        "-A", "--user-agent", type=str, metavar="STRING",
        default=f"dagger/{__import__('dagger').__version__}",
        help="User-Agent header",
    )
    req_group.add_argument(
        "--content-type", type=str, metavar="STRING",
        help="Override Content-Type header",
    )
    req_group.add_argument(
        "--follow-redirects", action="store_true", default=False,
        help="Follow HTTP redirects",
    )
    req_group.add_argument(
        "--verify-ssl", type=lambda v: v.lower() in ("true", "1", "yes"),
        default=True, metavar="BOOL",
        help="Verify TLS certificates (default: true)",
        dest="verify_ssl",
    )
    req_group.add_argument(
        "--no-verify-ssl", action="store_false", dest="verify_ssl",
        help="Disable TLS verification",
    )
    req_group.add_argument(
        "--timeout", type=validate_duration, default="30", metavar="SECONDS",
        help="Per-request timeout (default: 30s)",
    )
    req_group.add_argument(
        "--connect-timeout", type=validate_duration, default="10", metavar="SECONDS",
        help="Connection timeout (default: 10s)",
    )

    # Load group
    load_group = run_parser.add_argument_group("Load")
    load_group.add_argument(
        "-c", "--concurrency", type=validate_concurrency, default=10, metavar="N",
        help="Number of concurrent virtual users (default: 10)",
    )
    load_group.add_argument(
        "-r", "--rate", type=validate_rate, default=0, metavar="N",
        help="Max requests per second across all users (0=unlimited)",
    )
    load_group.add_argument(
        "-d", "--duration", type=validate_duration, default=None, metavar="TIME",
        help="Test duration (e.g., 30s, 5m, 1h). Use -n for request count instead.",
    )
    load_group.add_argument(
        "-n", "--requests", type=validate_positive_int, default=None, metavar="N",
        help="Total number of requests to send",
    )
    load_group.add_argument(
        "--ramp-up", type=validate_duration, default=None, metavar="TIME",
        help="Gradual ramp-up period (e.g., 10s)",
    )
    load_group.add_argument(
        "--ramp-down", type=validate_duration, default=None, metavar="TIME",
        help="Gradual ramp-down period",
    )
    load_group.add_argument(
        "--ramp-strategy", type=RampStrategy, choices=list(RampStrategy),
        default=RampStrategy.LINEAR, metavar="STRATEGY",
        help="Ramp strategy (default: linear)",
    )

    # Output group
    out_group = run_parser.add_argument_group("Output")
    out_group.add_argument(
        "-o", "--output", type=Path, default=None, metavar="DIR",
        help="Output directory for report files",
    )
    out_group.add_argument(
        "-f", "--format", type=validate_report_format, default="text",
        metavar="FMT", dest="output_formats",
        help="Report format: text, json, csv, html, all (default: text)",
    )
    out_group.add_argument(
        "--live-refresh", type=validate_positive_int, default=200, metavar="MS",
        help="Live display refresh interval in ms (default: 200)",
    )
    out_group.add_argument(
        "--no-live", action="store_true", default=False,
        help="Disable live updating display",
    )
    out_group.add_argument(
        "--no-summary", action="store_true", default=False,
        help="Suppress final summary report",
    )

    # Advanced group
    adv_group = run_parser.add_argument_group("Advanced")
    adv_group.add_argument(
        "--keep-alive", type=lambda v: v.lower() in ("true", "1", "yes"),
        default=True, metavar="BOOL",
        help="Reuse connections (default: true)",
    )
    adv_group.add_argument(
        "--no-keep-alive", action="store_false", dest="keep_alive",
        help="Disable connection reuse",
    )
    adv_group.add_argument(
        "--max-retries", type=validate_positive_int, default=0, metavar="N",
        help="Max retries on failure (default: 0)",
    )
    adv_group.add_argument(
        "--retry-delay", type=validate_duration, default="1", metavar="MS",
        help="Delay between retries in ms (default: 1000)",
    )
    adv_group.add_argument(
        "--proxy", type=str, default=None, metavar="URL",
        help="HTTP proxy for all requests",
    )
    adv_group.add_argument(
        "--save-responses", action="store_true", default=False,
        help="Save response bodies to output directory",
    )
    adv_group.add_argument(
        "--limit-response-size", type=validate_positive_int, default=1_048_576,
        metavar="BYTES", help="Truncate response bodies (default: 1MB)",
    )
    adv_group.add_argument(
        "--seed", type=int, default=None, metavar="N",
        help="Random seed for reproducible test patterns",
    )
    adv_group.add_argument(
        "--tags", type=str, default="", metavar="TAG1,TAG2",
        help="Comma-separated tags for this test run",
    )

    # ---- dagger config ----
    subparsers.add_parser(
        "config",
        help="Launch interactive configuration wizard",
        description="Interactive TUI wizard for building test configurations.",
    )

    # ---- dagger plugins ----
    plugins_parser = subparsers.add_parser(
        "plugins",
        help="Plugin management",
        description="Manage Dagger plugins.",
    )
    plugins_sub = plugins_parser.add_subparsers(dest="plugins_action")
    plugins_sub.add_parser("list", help="List installed plugins")
    info_parser = plugins_sub.add_parser("info", help="Show plugin details")
    info_parser.add_argument("name", type=str, help="Plugin name")

    # ---- dagger version ----
    subparsers.add_parser(
        "version",
        help="Show version and environment info",
    )

    # ---- dagger scan ----
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a Java project and rank its API endpoints by P95 latency",
        description="Static-scan a Spring Boot project's Controller layer, load-test "
                    "the discovered endpoints, and emit a slow-to-fast ranking report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan_parser.add_argument(
        "project_path", type=Path, metavar="PROJECT",
        help="Path to the Java project directory",
    )
    scan_parser.add_argument(
        "-b", "--base-url", type=str, required=True, metavar="URL",
        help="Target server base URL incl. protocol/host/port "
             "(e.g. http://localhost:8101/api)",
    )
    scan_parser.add_argument(
        "--git-diff", type=str, default=None, metavar="RANGE",
        help="Git range for incremental scan (e.g. main..HEAD)",
    )
    scan_parser.add_argument(
        "-c", "--max-parallel", type=int, default=5, metavar="N",
        help="Endpoints load-tested simultaneously (default: 5)",
    )
    scan_parser.add_argument(
        "--quick-requests", type=int, default=50, metavar="N",
        help="Phase-1 requests per endpoint (default: 50)",
    )
    scan_parser.add_argument(
        "-n", "--deep-requests", type=int, default=2000, metavar="N",
        help="Phase-2 requests per slow endpoint (default: 2000)",
    )
    scan_parser.add_argument(
        "--deep-threshold", type=float, default=20.0, metavar="N",
        help="Top-N slow endpoints entering phase 2 (count, or 0-1 fraction; default: 20)",
    )
    scan_parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, metavar="SECONDS",
        help="Per-request timeout in seconds (default: 30)",
    )
    scan_parser.add_argument(
        "-o", "--output", type=Path, default=Path("./perf_results"), metavar="DIR",
        help="Output directory (default: ./perf_results)",
    )
    scan_parser.add_argument(
        "--open", action="store_true", default=False,
        help="Open the HTML report in a browser after generation",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args, merge with config file, validate, return namespace."""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_root_parser()
    args = parser.parse_args(argv)

    # Handle --version
    if args.version:
        args.subcommand = "version"

    # Load and merge config file if specified
    if hasattr(args, "config_file") and args.config_file and args.config_file.exists():
        args = _merge_config_file(args)

    # If --version passed no subcommand, treat as 'version'
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    return args


def _merge_config_file(args: argparse.Namespace) -> argparse.Namespace:
    """Merge YAML/TOML config file values into args (CLI overrides file)."""
    path = args.config_file
    config_data = {}

    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        except ImportError:
            print("Warning: PyYAML not installed, cannot parse config file.", file=sys.stderr)
            return args
    elif path.suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(path, "rb") as f:
            config_data = tomllib.load(f) or {}

    if not config_data:
        return args

    # Extract nested sections
    target_cfg = config_data.get("target", {})
    load_cfg = config_data.get("load", {})
    request_cfg = config_data.get("request", {})
    output_cfg = config_data.get("output", {})

    # Apply config file values only if CLI arg is at default
    _apply_if_default(args, "url", target_cfg.get("url"))
    _apply_if_default(args, "method", target_cfg.get("method"))
    _apply_if_default(args, "concurrency", load_cfg.get("concurrency"))
    _apply_if_default(args, "rate", load_cfg.get("rate_limit") or load_cfg.get("rate"))
    _apply_if_default(args, "duration", load_cfg.get("duration"))
    _apply_if_default(args, "requests", load_cfg.get("total_requests"))
    _apply_if_default(args, "ramp_up", load_cfg.get("ramp_up"))
    _apply_if_default(args, "ramp_down", load_cfg.get("ramp_down"))
    _apply_if_default(args, "timeout", request_cfg.get("timeout"))
    _apply_if_default(args, "keep_alive", request_cfg.get("keep_alive"))
    _apply_if_default(args, "verify_ssl", request_cfg.get("verify_ssl"))
    _apply_if_default(args, "output", output_cfg.get("directory"))
    _apply_if_default(args, "tags", ",".join(config_data.get("tags", [])))

    return args


def _apply_if_default(args: argparse.Namespace, attr: str, value: Any) -> None:
    """Set attribute on args only if it wasn't explicitly set on CLI."""
    if value is None:
        return
    if not hasattr(args, attr):
        setattr(args, attr, value)
        return

    current = getattr(args, attr)
    # Check if current value is the argparse default
    # We use a simple heuristic: if the current value matches the default, override
    defaults = {
        "url": None,
        "method": HttpMethod.GET,
        "concurrency": 10,
        "rate": 0,
        "duration": None,
        "requests": None,
        "ramp_up": None,
        "ramp_down": None,
        "timeout": "30",
        "keep_alive": True,
        "verify_ssl": True,
        "output": None,
        "tags": "",
    }
    if attr in defaults and current == defaults[attr]:
        setattr(args, attr, value)


def build_config_from_args(args: argparse.Namespace) -> TestConfig:
    """Convert parsed CLI args into a validated TestConfig."""

    # Build TargetSpec
    target = TargetSpec(
        url=resolve_url(getattr(args, "url", "")),
        method=getattr(args, "method", HttpMethod.GET),
    )

    # Headers
    headers = {}
    if hasattr(args, "headers_raw") and args.headers_raw:
        for k, v in args.headers_raw:
            headers[k] = v
    if hasattr(args, "user_agent") and args.user_agent:
        headers.setdefault("User-Agent", args.user_agent)
    if hasattr(args, "content_type") and args.content_type:
        headers["Content-Type"] = args.content_type
    target.headers = headers

    # Body
    if hasattr(args, "data") and args.data:
        target.body = args.data.encode("utf-8")
    if hasattr(args, "json_body_raw") and args.json_body_raw:
        import json
        try:
            target.json_body = json.loads(args.json_body_raw)
        except json.JSONDecodeError:
            target.body = args.json_body_raw.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    # Form fields
    if hasattr(args, "form_fields_raw") and args.form_fields_raw:
        form = {}
        for item in args.form_fields_raw:
            if "=" in item:
                k, v = item.split("=", 1)
                form[k.strip()] = v.strip()
        target.form_fields = form

    # Cookies
    if hasattr(args, "cookies_raw") and args.cookies_raw:
        for item in args.cookies_raw:
            if "=" in item:
                k, v = item.split("=", 1)
                target.cookies[k.strip()] = v.strip()

    # Build TestConfig
    config = TestConfig(target=target)

    if hasattr(args, "concurrency"):
        config.concurrency = args.concurrency
    if hasattr(args, "rate"):
        config.rate_limit = args.rate

    # Duration / total requests
    if hasattr(args, "duration") and args.duration is not None:
        config.duration = timedelta(seconds=float(args.duration))
        config.total_requests = None
    if hasattr(args, "requests") and args.requests is not None:
        config.total_requests = args.requests
        if config.duration == timedelta(seconds=30) and hasattr(args, "duration") and args.duration is None:
            config.duration = None

    if hasattr(args, "ramp_up") and args.ramp_up is not None:
        config.ramp_up = timedelta(seconds=float(args.ramp_up))
    if hasattr(args, "ramp_down") and args.ramp_down is not None:
        config.ramp_down = timedelta(seconds=float(args.ramp_down))
    if hasattr(args, "ramp_strategy"):
        config.ramp_strategy = args.ramp_strategy

    # Request settings
    if hasattr(args, "timeout"):
        config.timeout = timedelta(seconds=float(args.timeout))
    if hasattr(args, "connect_timeout"):
        config.connect_timeout = timedelta(seconds=float(args.connect_timeout))
    if hasattr(args, "keep_alive"):
        config.keep_alive = args.keep_alive
    if hasattr(args, "verify_ssl"):
        config.verify_ssl = args.verify_ssl
    if hasattr(args, "follow_redirects"):
        config.follow_redirects = args.follow_redirects
    if hasattr(args, "max_retries"):
        config.max_retries = args.max_retries
    if hasattr(args, "retry_delay"):
        config.retry_delay = timedelta(seconds=float(args.retry_delay))
    if hasattr(args, "proxy"):
        config.proxy = args.proxy

    # Output settings
    if hasattr(args, "output") and args.output:
        config.output_dir = Path(args.output)
    if hasattr(args, "output_formats"):
        if isinstance(args.output_formats, str):
            from .validators import validate_report_format
            config.output_formats = validate_report_format(args.output_formats)
        else:
            config.output_formats = args.output_formats
    if hasattr(args, "live_refresh"):
        config.live_refresh_ms = args.live_refresh
    if hasattr(args, "no_live"):
        config.no_live = args.no_live
    if hasattr(args, "no_summary"):
        config.no_summary = args.no_summary
    if hasattr(args, "save_responses"):
        config.save_responses = args.save_responses
    if hasattr(args, "limit_response_size"):
        config.limit_response_size = args.limit_response_size

    # Tags
    if hasattr(args, "tags") and args.tags:
        config.tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    if hasattr(args, "seed") and args.seed is not None:
        config.seed = args.seed
    if hasattr(args, "plugin_dir"):
        config.plugin_dirs = list(args.plugin_dir)

    return config
