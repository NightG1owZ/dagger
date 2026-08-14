# 配置文件与交互式向导

Dagger 支持两种方式准备测试配置：

1. **配置文件**（YAML / TOML），通过 `--config-file` 加载。
2. **交互式向导** `dagger config`，引导式生成 YAML 配置。

两种方式的配置均可被 **CLI 参数覆盖**（命令行优先）。

---

## 配置文件

### 加载方式

```bash
dagger run --config-file dagger.yaml
```

支持 `.yaml` / `.yml` / `.toml`。

### 完整示例（dagger.yaml）

```yaml
# 目标
target:
  url: "https://httpbin.org/get"
  method: GET
  # headers:
  #   Authorization: "Bearer ${API_TOKEN}"
  #   Accept: "application/json"

# 负载
load:
  concurrency: 10
  duration: "30s"
  # total_requests: 10000        # 与 duration 二选一
  # ramp_up: "10s"
  # ramp_down: "5s"
  # ramp_strategy: linear        # linear | step
  # rate_limit: 100              # 每秒请求数上限 (0=不限)

# 请求级
request:
  # timeout: "30s"
  # connect_timeout: "10s"
  # keep_alive: true
  # verify_ssl: true
  # follow_redirects: false
  # max_retries: 3
  # retry_delay: "1000ms"

# 输出
output:
  # directory: "./results"
  formats: [text, json, html]
  # live_refresh_ms: 200
  # no_live: false

# 标签
tags: [example, smoke-test]

# 插件
# plugins:
#   auth_bearer:
#     token_endpoint: "https://auth.example.com/oauth/token"
#     client_id: "my-client"
#     client_secret: "my-secret"
#     refresh_interval: "300s"
```

### 字段说明

| 区块 | 字段 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `target` | `url` | string | 目标 URL |
| | `method` | string | HTTP 方法 |
| `load` | `concurrency` | int | 并发数 |
| | `duration` / `total_requests` | string / int | 时长 / 请求数（二选一） |
| | `ramp_up` / `ramp_down` | string | 加压 / 减压时长 |
| | `ramp_strategy` | string | `linear` / `step` |
| | `rate_limit` | int | 每秒请求上限 |
| `request` | `timeout` / `connect_timeout` | string | 超时 |
| | `keep_alive` / `verify_ssl` | bool | 连接复用 / 证书校验 |
| | `max_retries` / `retry_delay` | int / string | 重试 |
| `output` | `directory` | string | 输出目录 |
| | `formats` | list | 报告格式 |
| | `live_refresh_ms` / `no_live` | int / bool | 实时显示 |
| `tags` | — | list | 标签 |
| `plugins` | `<plugin>` | object | 插件配置 |

> 时长字段统一使用人类可读格式：`500ms`、`30s`、`5m`、`1h`。

### CLI 覆盖规则

CLI 参数优先级**高于**配置文件：只要在命令行显式传入（非默认值），就以命令行值为准。

```bash
# 复用配置，但把并发数改为 200
dagger run --config-file dagger.yaml -c 200
```

---

## 交互式向导 `dagger config`

```bash
dagger config
```

启动一个基于 `rich` 的 TUI 向导，逐步询问并生成 `dagger.yaml`：

1. **Target**：URL、HTTP 方法、自定义请求头、请求体类型（none/json/form/raw）。
2. **Load**：并发数、时长或请求数、是否加压（ramp-up / ramp-down / 策略）、限流。
3. **Output**：报告格式、是否保存到目录、是否显示实时进度。
4. **Meta**：标签。

完成后自动写入当前目录 `dagger.yaml`，并提示运行命令：

```text
Configuration saved to: ./dagger.yaml
Run: dagger run --config-file ./dagger.yaml
```

按 `Ctrl+C` 可随时取消向导。

### 指定输出路径

```bash
dagger config   # 默认写到 ./dagger.yaml
```

向导内部所有 `Confirm` / `Prompt` 均有默认值，直接回车即可快速生成一份可用配置。
