# `dagger run` — 压力测试命令

对单个目标 URL 发起并发 HTTP 请求，实时采集响应时间，并生成延迟分布报告。

## 命令格式

```bash
dagger run -u <URL> [选项]
```

`-u/--url` 是唯一必填参数；其余均有默认值。URL 省略协议时自动补 `https://`。

---

## 参数速查

### 目标（Target）

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `-u, --url URL` | — | 目标 URL（必填） |
| `-X, --method METHOD` | `GET` | HTTP 方法：GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS |

### 请求（Request）

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `-H, --header "K: V"` | — | 请求头，可重复 |
| `--data STRING` | — | 原始请求体字符串 |
| `--json JSON` | — | JSON 请求体（自动设置 Content-Type） |
| `--form KEY=VALUE` | — | 表单字段，可重复 |
| `-b, --cookie "k=v"` | — | Cookie，可重复 |
| `-A, --user-agent` | `dagger/0.1.0` | 自定义 User-Agent |
| `--content-type` | — | 覆盖 Content-Type |
| `--follow-redirects` | `false` | 跟随重定向 |
| `--verify-ssl` / `--no-verify-ssl` | `true` | 校验 / 跳过 TLS 证书 |
| `--timeout SECONDS` | `30` | 单请求总超时 |
| `--connect-timeout SECONDS` | `10` | 建连超时 |

### 负载（Load）

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `-c, --concurrency N` | `10` | 并发虚拟用户数 |
| `-r, --rate N` | `0` | 每秒请求数上限（0=不限） |
| `-d, --duration TIME` | — | 测试时长（如 `30s`/`5m`/`1h`） |
| `-n, --requests N` | — | 总请求数（与 `-d` 二选一） |
| `--ramp-up TIME` | — | 逐步加压时长 |
| `--ramp-down TIME` | — | 逐步减压时长 |
| `--ramp-strategy S` | `linear` | 加压策略：`linear` / `step` |

> `-d` 与 `-n` 互斥；两者都不指定时，默认按 **30 秒** 时长运行。

### 输出（Output）

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `-o, --output DIR` | — | 报告输出目录 |
| `-f, --format FMT` | `text` | 报告格式：`text`/`json`/`csv`/`html`/`all` |
| `--live-refresh MS` | `200` | 实时显示刷新间隔（毫秒） |
| `--no-live` | `false` | 关闭实时显示 |
| `--no-summary` | `false` | 关闭最终汇总报告 |

### 高级（Advanced）

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `--keep-alive` / `--no-keep-alive` | `true` | 复用连接 |
| `--max-retries N` | `0` | 失败重试次数 |
| `--retry-delay MS` | `1`（秒） | 重试初始间隔（指数退避 + 抖动） |
| `--proxy URL` | — | HTTP 代理 |
| `--save-responses` | `false` | 保存响应体到输出目录 |
| `--limit-response-size BYTES` | `1MB` | 响应体读取上限 |
| `--seed N` | — | 随机种子（复现测试模式） |
| `--tags TAG1,TAG2` | — | 本次测试的标签 |

---

## 常见示例

### 基础并发压测

```bash
# 50 并发，持续 60 秒
dagger run -u https://api.example.com/health -c 50 -d 60s
```

### 发送 JSON 请求体

```bash
dagger run -u https://api.example.com/api -X POST \
  --json '{"name":"dagger","version":"0.1"}' \
  -H "Authorization: Bearer xxx" \
  -c 20 -d 30s
```

### 表单 / 原始 body

```bash
# application/x-www-form-urlencoded
dagger run -u https://api.example.com/login -X POST \
  --form username=admin --form password=secret -c 10 -d 20s

# 原始字符串
dagger run -u https://api.example.com/upload -X POST \
  --data 'raw payload' --content-type text/plain -c 10 -d 20s
```

---

## 复杂功能示例

### 1. 请求数驱动（跑完 N 个请求即停）

```bash
# 总计发送 10000 个请求（不受时间限制）
dagger run -u https://api.example.com/api -c 100 -n 10000
```

### 2. 逐步加压（ramp-up / ramp-down）

```bash
# 前 30s 从 1 线性加到 100 并发，最后 10s 从 100 降到 1
dagger run -u https://api.example.com/api -c 100 -d 5m \
  --ramp-up 30s --ramp-down 10s --ramp-strategy linear
```

- `linear`：并发用户数随时间**线性**变化。
- `step`：按 25% 阶梯跳跃式变化（更贴近突发流量）。

### 3. 限流（令牌桶）

```bash
# 全局限速 100 req/s，避免打垮目标
dagger run -u https://api.example.com/api -c 50 -d 60s --rate 100
```

令牌桶以 `asyncio.Lock` 保护，跨所有虚拟用户共享，保证平滑发流。

### 4. 失败重试（指数退避 + 抖动）

```bash
# 失败最多重试 3 次，初始间隔 500ms，逐次翻倍并加随机抖动
dagger run -u https://api.example.com/api -c 10 -d 60s \
  --max-retries 3 --retry-delay 500ms
```

### 5. 跳过 TLS 校验 / 走代理

```bash
# 自签名证书环境
dagger run -u https://internal.example.com -c 10 -d 30s --no-verify-ssl

# 通过代理
dagger run -u https://api.example.com -c 10 -d 30s --proxy http://127.0.0.1:8888
```

### 6. 多格式报告 + 自定义请求头

```bash
dagger run -u https://api.example.com/api -c 100 -d 2m \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/json" \
  -f text,json,html -o ./results --tags smoke,prod
```

---

## 优雅退出

| 操作 | 行为 |
| :--- | :--- |
| 第一次 `Ctrl+C` | 优雅退出：停止新请求，排空在途请求后汇总 |
| 第二次 `Ctrl+C` | 立即中止 |

---

## 指标说明

压测过程实时采集以下指标，详见 [reports.md](reports.md)：

- **延迟**：min / P50 / P75 / P90 / P95 / P99 / P99.9 / max / mean / stddev
- **吞吐**：平均 RPS、峰值 RPS、收/发字节数
- **状态码分布**：各 HTTP 状态码计数与占比
- **错误分析**：错误类型聚合、占比、样例
- **时间序列**：每秒的 RPS、P50/P90/P99、错误率
- **延迟直方图**：HDR 风格对数线性分桶（1ms ~ 60s）
