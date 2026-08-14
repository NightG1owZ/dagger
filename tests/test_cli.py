"""Tests for the click CLI wiring."""

import json

from click.testing import CliRunner

from perfscanner.cli import cli


def test_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_start_help():
    result = CliRunner().invoke(cli, ["start", "--help"])
    assert result.exit_code == 0
    assert "--base-url" in result.output
    assert "--max-parallel" in result.output
    assert "--deep-requests" in result.output


def test_start_end_to_end(sample_java_project, local_server, tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "start",
            str(sample_java_project),
            "--base-url",
            local_server,
            "-c", "2",
            "-q", "5",
            "-n", "10",
            "--deep-threshold", "2",
            "-o", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    json_path = tmp_path / "report_data.json"
    html_path = tmp_path / "report.html"
    assert json_path.exists()
    assert html_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_endpoints"] == 5
    # slowest-first ordering is present in the ranking
    assert data["endpoints"][0]["rank"] == 1
