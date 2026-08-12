## Key Features Delivered

| Feature | Implementation |
|---------|----------------|
| HTTP methods | GET / POST / PUT / DELETE / PATCH / HEAD / OPTIONS |
| Request config | Headers, JSON / form / raw body, cookies, custom user-agent |
| Concurrency | Async IO via `aiohttp`, each user = `asyncio.Task` |
| Rate limiting | Token bucket algorithm with shared `asyncio.Lock` |
| Ramp strategies | Linear + step ramp‑up / ramp‑down |
| Test duration | Duration‑based (`-d 30s`) or request‑count‑based (`-n 10000`) |
| Live display | `rich.Live` table with real‑time RPS, latencies, error rate |
| Reports | Text (terminal), JSON, CSV, self‑contained HTML with Chart.js |
| Plugins | ABC‑based + `setuptools` entry_points discovery |
| Interactive mode | `dagger config` — rich‑based TUI wizard |
| Config file | YAML format with CLI override |
| Graceful shutdown | First Ctrl+C = drain; second = abort |

---

## CLI Usage Examples

```bash
# run
python -m dagger

# Root help
dagger --help

# Basic load test: 50 users for 60 seconds
dagger run -u URL -c 50 -d 60s

# POST request with JSON body
dagger run -u URL -X POST --json '{"key":"value"}' -c 10 -d 30s

# Extended test with ramp‑up and HTML report
dagger run -u URL -c 100 -d 5m --ramp-up 30s -f html -o ./results

# Launch interactive configuration wizard
dagger config

# List installed plugins
dagger plugins list

# Run from a YAML config file
dagger run --config-file dagger.yaml
```

---

> 提示：所有 CLI 示例中的 `URL` 请替换为实际目标地址，参数可根据需要调整。