"""Interactive configuration wizard using rich prompts."""

import sys
from pathlib import Path

from ..utils.misc import parse_duration, resolve_url
from ..models.enums import HttpMethod, ReportFormat, RampStrategy


def run_interactive_config(output_path: Path | None = None) -> None:
    """Launch interactive TUI wizard to build a dagger.yaml config file."""
    try:
        from rich.console import Console
        from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print("Error: 'rich' library is required for interactive mode.")
        print("Install with: pip install rich")
        sys.exit(1)

    console = Console()
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Dagger Interactive Configuration Wizard[/bold cyan]\n\n"
        "This wizard will help you create a test configuration file.\n"
        "Press Ctrl+C at any time to cancel.",
        border_style="cyan",
    ))
    console.print()

    config: dict = {"target": {}, "load": {}, "request": {}, "output": {}, "tags": [], "plugins": {}}

    # Target
    console.print("[bold]1. Target Configuration[/bold]")
    url = Prompt.ask("  Target URL", default="https://httpbin.org/get")
    config["target"]["url"] = resolve_url(url)

    method_str = Prompt.ask(
        "  HTTP Method",
        choices=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        default="GET",
    )
    config["target"]["method"] = method_str

    add_headers = Confirm.ask("  Add custom headers?", default=False)
    if add_headers:
        headers = {}
        console.print("  [dim]Enter headers as 'Key: Value'. Empty line to finish.[/dim]")
        while True:
            hdr = Prompt.ask("  Header", default="")
            if not hdr:
                break
            if ":" in hdr:
                k, v = hdr.split(":", 1)
                headers[k.strip()] = v.strip()
            else:
                console.print("  [red]Invalid format. Use 'Key: Value'[/red]")
        if headers:
            config["target"]["headers"] = headers

    body_type = Prompt.ask(
        "  Request body type",
        choices=["none", "json", "form", "raw"],
        default="none",
    )
    if body_type == "json":
        json_str = Prompt.ask("  JSON body", default='{"key": "value"}')
        import json
        try:
            config["target"]["json_body"] = json.loads(json_str)
        except json.JSONDecodeError:
            config["target"]["body"] = json_str
    elif body_type == "form":
        fields = {}
        console.print("  [dim]Enter form fields as 'key=value'. Empty to finish.[/dim]")
        while True:
            fld = Prompt.ask("  Field", default="")
            if not fld:
                break
            if "=" in fld:
                k, v = fld.split("=", 1)
                fields[k.strip()] = v.strip()
        if fields:
            config["target"]["form_fields"] = fields
    elif body_type == "raw":
        config["target"]["body"] = Prompt.ask("  Raw body text", default="")

    # Load
    console.print()
    console.print("[bold]2. Load Configuration[/bold]")
    config["load"]["concurrency"] = IntPrompt.ask("  Concurrent users", default=10)

    use_duration = Confirm.ask("  Use duration-based test?", default=True)
    if use_duration:
        config["load"]["duration"] = Prompt.ask("  Duration (e.g., 30s, 5m, 1h)", default="30s")
    else:
        config["load"]["total_requests"] = IntPrompt.ask("  Total requests to send", default=1000)

    use_ramp = Confirm.ask("  Use ramp-up period?", default=False)
    if use_ramp:
        config["load"]["ramp_up"] = Prompt.ask("  Ramp-up duration", default="10s")
        ramp_strat = Prompt.ask(
            "  Ramp strategy",
            choices=["linear", "step"],
            default="linear",
        )
        config["load"]["ramp_strategy"] = ramp_strat

    use_ramp_down = Confirm.ask("  Use ramp-down period?", default=False)
    if use_ramp_down:
        config["load"]["ramp_down"] = Prompt.ask("  Ramp-down duration", default="10s")

    rate_limit = IntPrompt.ask("  Rate limit (req/s, 0=unlimited)", default=0)
    if rate_limit > 0:
        config["load"]["rate_limit"] = rate_limit

    # Output
    console.print()
    console.print("[bold]3. Output Configuration[/bold]")
    fmt_str = Prompt.ask(
        "  Report format(s)",
        choices=["text", "json", "csv", "html", "text,json", "text,html", "text,json,html", "all"],
        default="text",
    )
    config["output"]["formats"] = [f.strip() for f in fmt_str.split(",")]

    save_output = Confirm.ask("  Save reports to a directory?", default=False)
    if save_output:
        config["output"]["directory"] = Prompt.ask("  Output directory", default="./results")

    config["output"]["no_live"] = not Confirm.ask("  Show live progress display?", default=True)

    # Tags
    console.print()
    console.print("[bold]4. Meta[/bold]")
    tags_str = Prompt.ask("  Tags (comma-separated)", default="")
    if tags_str:
        config["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

    # Build and save
    console.print()
    console.print("[bold green]Configuration complete![/bold green]")

    output_path = output_path or Path.cwd() / "dagger.yaml"
    yaml_content = _build_yaml(config)
    output_path.write_text(yaml_content, encoding="utf-8")
    console.print(f"\n[bold]Configuration saved to:[/bold] {output_path}")
    console.print(f"Run: [cyan]dagger run --config-file {output_path}[/cyan]")


def _build_yaml(config: dict, indent: int = 0) -> str:
    """Simple YAML builder for the generated config."""
    lines = []
    prefix = "  " * indent

    for key, value in config.items():
        if isinstance(value, dict):
            if not value:
                continue
            lines.append(f"{prefix}{key}:")
            lines.append(_build_yaml(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                continue
            items = ", ".join(repr(item) for item in value)
            lines.append(f"{prefix}{key}: [{items}]")
        elif isinstance(value, str):
            if any(c in value for c in ':{}[]&*?|>!%@`,'):
                lines.append(f'{prefix}{key}: "{value}"')
            else:
                lines.append(f"{prefix}{key}: {value}")
        elif value is not None:
            lines.append(f"{prefix}{key}: {value}")

    return "\n".join(lines)
