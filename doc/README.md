# Dagger 使用文档

> Dagger —— HTTP API 压力测试 CLI 工具，提供与 JMeter 相当的功能，采用 sqlmap 风格的命令行界面。

Dagger 是一个基于 Python 的本地化接口压测工具，同时集成了 **PerfScanner**（Java 项目接口性能扫描与排名）能力。它通过一个统一的 `dagger` 命令，覆盖两大场景：

1. **通用 HTTP 压测**（`dagger run`）—— 对单个接口发起并发请求，输出 P95/P99 等延迟指标。
2. **Java 接口扫描压测**（`dagger scan`）—— 静态扫描 Spring Boot 项目 Controller 层，全量/增量压测并生成从慢到快的接口排名。

---

## 目录

| 主题 | 文档 | 说明 |
| :--- | :--- | :--- |
| 快速开始 | 本页 | 安装与基础命令 |
| 压测命令 | [run.md](run.md) | `dagger run` 全部参数与复杂功能示例 |
| 接口扫描 | [scan.md](scan.md) | `dagger scan`（PerfScanner）完整说明 |
| 配置文件 | [config.md](config.md) | YAML/TOML 配置 + 交互式向导 |
| 报告格式 | [reports.md](reports.md) | text / json / csv / html 四种产物 |
| 插件系统 | [plugins.md](plugins.md) | 插件机制与内置插件 |

---

## 特性总览

| 特性 | 说明 |
| :--- | :--- |
| HTTP 方法 | GET / POST / PUT / DELETE / PATCH / HEAD / OPTIONS |
| 请求配置 | 请求头、JSON / 表单 / 原始 body、Cookie、自定义 User-Agent |
| 并发模型 | 基于 `aiohttp` + `asyncio`，每个虚拟用户是一个 `asyncio.Task` |
| 限流 | 令牌桶算法（共享 `asyncio.Lock`），`-r` 限制每秒请求数 |
| 加压策略 | 线性 / 阶梯式 ramp-up、ramp-down |
| 测试时长 | 时长驱动（`-d 30s`）或请求数驱动（`-n 10000`） |
| 实时显示 | `rich.Live` 表格实时展示 RPS、延迟、错误率、状态码 |
| 报告 | 终端文本、JSON、CSV、自包含 HTML（Chart.js） |
| 插件 | ABC 基类 + `setuptools` entry_points 发现机制 |
| 交互模式 | `dagger config` —— 基于 rich 的 TUI 配置向导 |
| 配置文件 | YAML / TOML 格式，CLI 参数可覆盖 |
| 优雅退出 | 第一次 Ctrl+C 排空在途请求，第二次立即中止 |
| Java 扫描 | `dagger scan` 扫描 Controller → 两阶段压测 → 慢接口排名 |

---

## 安装

```bash
# 依赖（Python >= 3.11）
pip install -e .

# 或手动安装依赖
pip install aiohttp rich pyyaml jinja2 javalang click
```

安装后可直接使用 `dagger` 命令，也可用 `python -m dagger` 等效调用。

```bash
dagger --help          # 根命令帮助
dagger --version       # 版本信息
```

---

## 快速开始

### 1. 基础压测：50 并发持续 60 秒

```bash
dagger run -u https://httpbin.org/get -c 50 -d 60s
```

### 2. POST + JSON 请求体

```bash
dagger run -u https://httpbin.org/post -X POST --json '{"key":"value"}' -c 10 -d 30s
```

### 3. 带加压与 HTML 报告

```bash
dagger run -u https://httpbin.org/get -c 100 -d 5m --ramp-up 30s -f html -o ./results
```

### 4. 扫描 Java 项目并对接口排名

```bash
dagger scan ./spring-boot-project --base-url http://localhost:8101/api
```

### 5. 交互式生成配置

```bash
dagger config
```

---

## 命令总览

```text
dagger [全局选项] <子命令> [参数]

子命令:
  run       运行一次压力测试
  scan      扫描 Java 项目并按 P95 延迟排名接口
  config    交互式配置向导
  plugins   插件管理 (list / info)
  version   显示版本与环境信息

全局选项:
  --version            显示版本
  -v, --verbose        提高日志级别 (-v, -vv, -vvv)
  -q, --quiet          静默模式（仅输出错误）
  --no-color           禁用彩色输出
  --config-file PATH   YAML/TOML 配置文件
  --plugin-dir PATH    额外的插件搜索路径（可重复）
```

---

## 项目结构

```text
dagger/
├── cli/          命令行解析、校验、交互向导、启动 banner
├── core/         压测引擎（engine/worker/requestor/session/throttle/timer）
├── models/       配置、目标、指标、结果等数据模型
├── reporting/    实时显示、汇总、text/json/csv/html 导出器
├── plugins/      插件基类、管理器、内置插件
├── dist/         分布式测试接口（预留）
└── utils/        日志、信号处理、工具函数

perfscanner/      接口扫描压测（dagger scan 实现）
├── scanner.py    Java Controller 静态扫描
├── engine.py     两阶段压测引擎
├── analyzer.py   P95/P99 计算与排序
├── reporter.py   JSON + HTML 报告
└── core.py       编排逻辑
```
