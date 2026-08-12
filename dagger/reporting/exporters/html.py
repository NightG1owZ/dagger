"""HTML report exporter using Jinja2 templates."""

import json
from pathlib import Path

from ...models.metrics import MetricsSummary


class HtmlExporter:
    """Renders a self-contained HTML report from a MetricsSummary."""

    def __init__(self, template_dir: Path | None = None):
        if template_dir is None:
            template_dir = Path(__file__).parent.parent.parent / "templates"
        self._template_dir = template_dir

    def export(self, summary: MetricsSummary, filepath: Path) -> None:
        # Load template
        template_path = self._template_dir / "report.html"
        if not template_path.exists():
            # Fall back to inline rendering
            html = self._render_inline(summary)
        else:
            try:
                from jinja2 import Environment, FileSystemLoader
                env = Environment(loader=FileSystemLoader(str(self._template_dir)))
                template = env.get_template("report.html")
                html = template.render(**self._build_template_data(summary))
            except ImportError:
                html = self._render_inline(summary)

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(html, encoding="utf-8")

    def _build_template_data(self, summary: MetricsSummary) -> dict:
        return {
            "config": summary.config_summary,
            "duration": round(summary.duration, 2),
            "total_requests": summary.total_requests,
            "successful": summary.successful,
            "failed": summary.failed,
            "success_rate": round(summary.success_rate, 2),
            "avg_rps": round(summary.avg_rps, 2),
            "peak_rps": round(summary.peak_rps, 2),
            "latencies": {
                "min": round(summary.latencies.min, 2),
                "p50": round(summary.latencies.p50, 2),
                "p75": round(summary.latencies.p75, 2),
                "p90": round(summary.latencies.p90, 2),
                "p95": round(summary.latencies.p95, 2),
                "p99": round(summary.latencies.p99, 2),
                "p99_9": round(summary.latencies.p99_9, 2),
                "max": round(summary.latencies.max, 2),
                "mean": round(summary.latencies.mean, 2),
            },
            "status_codes": {str(k): v for k, v in summary.status_codes.items()},
            "errors": [
                {"type": e.error_type, "count": e.count, "percentage": round(e.percentage, 2)}
                for e in summary.errors
            ],
            "bytes_received": summary.bytes_received,
            "histogram_json": json.dumps([
                {"x": f"{b:.0f}ms" if b != float("inf") else "inf", "y": c}
                for b, c in summary.histogram_buckets
            ]),
            "timeseries_json": json.dumps([
                {"elapsed": round(p.elapsed, 1), "rps": round(p.rps, 2), "error_rate": round(p.error_rate, 2)}
                for p in summary.time_series
            ]),
            "p50_series_json": json.dumps([
                {"elapsed": round(p.elapsed, 1), "value": round(p.p50, 2)}
                for p in summary.time_series
            ]),
        }

    def _render_inline(self, summary: MetricsSummary) -> str:
        """Generate a minimal HTML report without Jinja2."""
        data = self._build_template_data(summary)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dagger Stress Test Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
h1 {{ color: #00d4ff; margin-bottom: 20px; }}
h2 {{ color: #aaa; margin: 30px 0 15px; font-size: 1.1em; text-transform: uppercase; letter-spacing: 1px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 30px; }}
.card {{ background: #16213e; border-radius: 10px; padding: 20px; text-align: center; }}
.card .value {{ font-size: 1.8em; font-weight: bold; color: #00d4ff; }}
.card .label {{ font-size: 0.85em; color: #888; margin-top: 5px; }}
.chart-container {{ background: #16213e; border-radius: 10px; padding: 20px; margin-bottom: 20px; max-width: 100%; }}
.chart-container canvas {{ max-height: 300px; }}
table {{ width: 100%; border-collapse: collapse; background: #16213e; border-radius: 10px; overflow: hidden; margin-bottom: 20px; }}
th, td {{ padding: 12px 16px; text-align: left; }}
th {{ background: #0f3460; color: #00d4ff; font-weight: 600; }}
tr:not(:last-child) td {{ border-bottom: 1px solid #1a1a3e; }}
.success {{ color: #4caf50; }}
.error {{ color: #f44336; }}
.footer {{ text-align: center; color: #666; margin-top: 30px; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>Dagger Stress Test Report</h1>

<div class="cards">
<div class="card"><div class="value">{data['total_requests']}</div><div class="label">Total Requests</div></div>
<div class="card"><div class="value success">{data['success_rate']:.1f}%</div><div class="label">Success Rate</div></div>
<div class="card"><div class="value">{data['avg_rps']:.1f}</div><div class="label">Avg RPS</div></div>
<div class="card"><div class="value">{data['peak_rps']:.1f}</div><div class="label">Peak RPS</div></div>
<div class="card"><div class="value">{data['latencies']['p95']:.0f} ms</div><div class="label">P95 Latency</div></div>
<div class="card"><div class="value">{data['latencies']['p99']:.0f} ms</div><div class="label">P99 Latency</div></div>
</div>

<h2>Latency Distribution</h2>
<div class="chart-container"><canvas id="latencyChart"></canvas></div>

<h2>RPS Over Time</h2>
<div class="chart-container"><canvas id="rpsChart"></canvas></div>

<h2>Latency Percentiles</h2>
<table>
<tr><th>Percentile</th><th>Value (ms)</th></tr>
<tr><td>Min</td><td>{data['latencies']['min']:.1f}</td></tr>
<tr><td>P50</td><td>{data['latencies']['p50']:.1f}</td></tr>
<tr><td>P75</td><td>{data['latencies']['p75']:.1f}</td></tr>
<tr><td>P90</td><td>{data['latencies']['p90']:.1f}</td></tr>
<tr><td>P95</td><td>{data['latencies']['p95']:.1f}</td></tr>
<tr><td>P99</td><td>{data['latencies']['p99']:.1f}</td></tr>
<tr><td>P99.9</td><td>{data['latencies']['p99_9']:.1f}</td></tr>
<tr><td>Max</td><td>{data['latencies']['max']:.1f}</td></tr>
<tr><td>Mean</td><td>{data['latencies']['mean']:.1f}</td></tr>
</table>

<div class="footer">Generated by Dagger v0.1.0</div>

<script>
const latencyCtx = document.getElementById('latencyChart').getContext('2d');
new Chart(latencyCtx, {{
  type: 'bar',
  data: {{
    labels: {data['histogram_json']}.map(d => d.x),
    datasets: [{{
      label: 'Request Count',
      data: {data['histogram_json']}.map(d => d.y),
      backgroundColor: '#00d4ff',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#333' }} }},
      y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#333' }} }}
    }}
  }}
}});

const rpsCtx = document.getElementById('rpsChart').getContext('2d');
new Chart(rpsCtx, {{
  type: 'line',
  data: {{
    labels: {data['timeseries_json']}.map(d => d.elapsed + 's'),
    datasets: [
      {{
        label: 'RPS',
        data: {data['timeseries_json']}.map(d => d.rps),
        borderColor: '#00d4ff',
        backgroundColor: 'rgba(0, 212, 255, 0.1)',
        fill: true,
        tension: 0.3,
        yAxisID: 'y',
      }},
      {{
        label: 'Error Rate %',
        data: {data['timeseries_json']}.map(d => d.error_rate),
        borderColor: '#f44336',
        backgroundColor: 'rgba(244, 67, 54, 0.1)',
        fill: true,
        tension: 0.3,
        yAxisID: 'y1',
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ position: 'top', labels: {{ color: '#aaa' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#333' }} }},
      y: {{ type: 'linear', position: 'left', ticks: {{ color: '#00d4ff' }}, grid: {{ color: '#333' }}, title: {{ display: true, text: 'RPS', color: '#00d4ff' }} }},
      y1: {{ type: 'linear', position: 'right', ticks: {{ color: '#f44336', callback: v => v + '%' }}, grid: {{ display: false }}, title: {{ display: true, text: 'Error Rate', color: '#f44336' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
