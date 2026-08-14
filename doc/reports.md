# 报告格式

`dagger run` 支持四种报告格式，通过 `-f` 指定，可组合输出：

| 格式 | `-f` 值 | 产物 | 用途 |
| :--- | :--- | :--- | :--- |
| 文本 | `text` | 终端输出 | 快速查看 |
| JSON | `json` | `dagger_report_<时间戳>.json` | 机器可读 / CI 集成 |
| CSV | `csv` | `dagger_report_<时间戳>.csv` | 外部数据分析 |
| HTML | `html` | `dagger_report_<时间戳>.html` | 分享 / 可视化 |

```bash
# 全部输出
dagger run -u https://api.example.com -c 10 -d 30s -f all -o ./results

# 只输出 JSON + HTML
dagger run -u https://api.example.com -c 10 -d 30s -f json,html
```

文件命名格式：`dagger_report_YYYYMMDDTHHMMSSZ.<ext>`（UTC 时间戳）。

---

## 采集指标

| 指标 | 说明 |
| :--- | :--- |
| 延迟百分位 | min / P50 / P75 / P90 / P95 / P99 / P99.9 / max / mean / stddev（毫秒） |
| 吞吐 | 平均 RPS、峰值 RPS、接收/发送字节数 |
| 状态码分布 | 各 HTTP 状态码计数与占比 |
| 错误分析 | 错误类型（ConnectionError / Timeout / ...）、数量、占比、样例 |
| 时间序列 | 每秒的 RPS、P50/P90/P99、错误率 |
| 延迟直方图 | HDR 风格对数线性分桶（1ms ~ 60s） |

---

## 1. 文本报告（text）

在终端直接打印，包含五个区块：

```
╭──────── DAGGER STRESS TEST REPORT ────────╮
Overview           目标/方法/并发/时长/请求数/RPS/成功率
Latency Distribution   Min/P50/P75/P90/P95/P99/P99.9/Max/StdDev
Status Code Distribution  各状态码计数与占比
Throughput          平均/峰值 RPS、收发字节、总时长
Error Analysis      错误类型、数量、占比、样例
Latency Distribution  文本直方图（█ 柱状）
```

```bash
dagger run -u https://api.example.com -c 10 -d 30s -f text
```

---

## 2. JSON 报告（json）

自描述的机器可读结构，适合 CI / 脚本解析：

```json
{
  "config": { "url": "...", "method": "GET", "concurrency": 10, "duration": 30 },
  "total_requests": 1234,
  "successful": 1200,
  "failed": 34,
  "success_rate": 97.24,
  "avg_rps": 41.1,
  "peak_rps": 58.3,
  "latency_ms": { "min": 12.0, "p50": 45.2, "p95": 128.6, "p99": 210.4, "p99_9": 310.2, "max": 512.0, "mean": 52.1, "stddev": 30.0 },
  "status_codes": { "200": 1200, "502": 34 },
  "errors": [ { "type": "Timeout", "count": 20, "percentage": 1.6, "example": "..." } ],
  "bytes_received": 204800,
  "bytes_sent": 8192,
  "histogram_buckets": [ { "boundary_ms": 10.0, "count": 100 }, { "boundary_ms": "inf", "count": 3 } ],
  "time_series": [ { "elapsed": 1.0, "rps": 40.0, "p50_ms": 45.0, "p90_ms": 90.0, "p99_ms": 200.0, "error_rate": 0.5 } ]
}
```

---

## 3. CSV 报告（csv）

逐秒时间序列，便于导入 Excel / pandas：

```csv
elapsed_seconds,rps,p50_ms,p90_ms,p99_ms,error_rate_pct
1.0,40.0,45.0,90.0,200.0,0.5
2.0,42.1,44.8,88.0,195.0,0.0
...
```

---

## 4. HTML 报告（html）

自包含的单文件报告（`<script>` 内联 Chart.js CDN），包含：

- **总览卡片**：请求数、成功率、平均/峰值 RPS、P95 延迟
- **延迟分布柱状图**：Chart.js 渲染直方图
- **RPS / 错误率时间序列**：双轴折线图
- **延迟百分位表**：Min/P50/P75/P90/P95/P99/P99.9/Max/Mean

```bash
dagger run -u https://api.example.com -c 100 -d 5m -f html -o ./results
```

双击生成的 HTML 即可在浏览器查看，无需本地 Web 服务器。

---

## 相关命令

- 实时显示（非最终报告）：`rich.Live` 表格，`--live-refresh` 控制刷新，`--no-live` 关闭。
- 关闭汇总：`--no-summary`。
- 保存响应体：`--save-responses`（与报告目录配合使用）。
