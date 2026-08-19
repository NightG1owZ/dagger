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

dagger scan D:\31124\Devtools\DASH\glow\src\main\java\com\night\glow\controller --base-url http://localhost:8101/api -c 5 --quick-requests 50 -n 2000 --deep-threshold 20 -t 30 -o ./perf_results
```

---

> 提示：所有 CLI 示例中的 `URL` 请替换为实际目标地址，参数可根据需要调整。

---

## OpenAPI 压测工具（`java/`）

针对 Java Spring 服务的独立压测工具：给定 **OpenAPI 文档 URL**（如
`http://localhost:8101/api/v3/api-docs`），自动解析接口、按 Schema 生成测试数据、
冒烟预检、并发压测并按 **P95 从高到低** 输出排名（含 P99、失败原因、JSON/CSV 报告）。

按"一个语言一个文件夹"规划自包含于 `java/`（后续其他语言工具建平级目录）：

```bash
# 压测 OpenAPI 文档中的全部接口，跳过冒烟失败的接口
python -m java --openapi-url http://localhost:8101/api/v3/api-docs \
    --concurrency 20 --total-requests 500 --skip-error-apis \
    --output ./java/results/report.json
```

详见 [java/README.md](java/README.md)。