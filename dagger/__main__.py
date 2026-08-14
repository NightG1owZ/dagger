"""Dagger entry point — python -m dagger or `dagger` command."""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .cli.banner import show_banner
from .cli.parser import parse_args, build_config_from_args
from .utils.logger import setup_logging


def main() -> None:
    """Main entry point for the dagger CLI."""
    args = parse_args()

    # Handle subcommands that don't need the engine
    if args.subcommand == "version":
        show_banner()
        print(f"Python: {sys.version}")
        print(f"Platform: {sys.platform}")
        return

    if args.subcommand == "config":
        from .cli.interactive import run_interactive_config
        run_interactive_config()
        return

    if args.subcommand == "plugins":
        _handle_plugins(args)
        return

    if args.subcommand == "run":
        setup_logging(
            verbosity=getattr(args, "verbose", 0),
            quiet=getattr(args, "quiet", False),
        )
        show_banner()
        asyncio.run(_run_test(args))
        return

    if args.subcommand == "scan":
        if not args.project_path.exists():
            print(f"Error: project path does not exist: {args.project_path}", file=sys.stderr)
            return
        asyncio.run(_run_scan(args))
        return

    # No subcommand or unknown
    print("Usage: dagger [run|scan|config|plugins|version] [OPTIONS]")
    print("Try 'dagger --help' for more information.")


def _handle_plugins(args) -> None:
    """Handle plugin subcommands."""
    from .plugins.manager import PluginManager

    pm = PluginManager(getattr(args, "plugin_dir", []))
    action = getattr(args, "plugins_action", "list")

    if action == "list":
        plugins = pm.list_plugins()
        if not plugins:
            print("No plugins discovered.")
            return
        print(f"{'Name':<25} {'Version':<10} {'Status':<10} Description")
        print("-" * 70)
        for p in plugins:
            status = "loaded" if p["loaded"] else "available"
            print(f"{p['name']:<25} {p['version']:<10} {status:<10} {p['description']}")

    elif action == "info":
        name = getattr(args, "name", None)
        if not name:
            print("Usage: dagger plugins info NAME")
            return
        plugins = pm.list_plugins()
        for p in plugins:
            if p["name"] == name:
                print(f"Name:        {p['name']}")
                print(f"Version:     {p['version']}")
                print(f"Description: {p['description']}")
                print(f"Loaded:      {p['loaded']}")
                return
        print(f"Plugin not found: {name}")


async def _run_test(args) -> None:
    """Execute the test engine with CLI args."""
    from .core.engine import TestEngine
    from .reporting.live import LiveDisplay
    from .reporting.summary import SummaryBuilder
    from .reporting.exporters.text import TextExporter
    from .reporting.exporters.json_export import JsonExporter
    from .reporting.exporters.csv_export import CsvExporter
    from .reporting.exporters.html import HtmlExporter
    from .models.enums import ReportFormat

    # Build config
    config = build_config_from_args(args)

    # Set up live display
    display = None
    if not config.no_live:
        from rich.console import Console
        console = Console(no_color=getattr(args, "no_color", False))
        display = LiveDisplay(
            console=console,
            refresh_per_second=max(1, 1000 // config.live_refresh_ms),
        )
        display.start()

    # Create and run engine
    engine = TestEngine(
        config=config,
        display_callback=display.async_update if display else None,
    )

    try:
        summary = await engine.run()
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        return
    finally:
        if display:
            display.stop()

    # Generate reports
    if not config.no_summary:
        _export_reports(summary, config)


async def _run_scan(args) -> None:
    """Scan a Java project and rank endpoints by P95 latency."""
    from perfscanner.core import run_scan

    await run_scan(
        args.project_path,
        args.base_url,
        git_diff=args.git_diff,
        max_parallel=args.max_parallel,
        quick_requests=args.quick_requests,
        deep_requests=args.deep_requests,
        deep_threshold=args.deep_threshold,
        timeout=args.timeout,
        output=args.output,
        open_browser=args.open,
    )


def _export_reports(summary, config) -> None:
    """Export reports in all configured formats."""
    from .reporting.exporters.text import TextExporter
    from .reporting.exporters.json_export import JsonExporter
    from .reporting.exporters.csv_export import CsvExporter
    from .reporting.exporters.html import HtmlExporter
    from .models.enums import ReportFormat

    output_dir = config.output_dir or Path.cwd() / "dagger_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"dagger_report_{timestamp}"

    for fmt in config.output_formats:
        if fmt == ReportFormat.TEXT:
            exporter = TextExporter()
            exporter.export(summary)

        elif fmt == ReportFormat.JSON:
            filepath = output_dir / f"{base_name}.json"
            exporter = JsonExporter()
            exporter.export(summary, filepath)
            print(f"JSON report saved to: {filepath}")

        elif fmt == ReportFormat.CSV:
            filepath = output_dir / f"{base_name}.csv"
            exporter = CsvExporter()
            exporter.export(summary, filepath)
            print(f"CSV report saved to: {filepath}")

        elif fmt == ReportFormat.HTML:
            filepath = output_dir / f"{base_name}.html"
            exporter = HtmlExporter()
            exporter.export(summary, filepath)
            print(f"HTML report saved to: {filepath}")


if __name__ == "__main__":
    main()
