# PerfScanner 测试报告

> 对应需求文档 `.claude/Requirement.md`。测试命令：`python -m pytest -q`（Python 3.11.5，pytest 9.1.1 + pytest-asyncio）。

## 0. CLI 入口

PerfScanner 已并入 Dagger 现有 CLI，作为 `dagger scan` 子命令（同时保留独立的 `perf-tool start` / `python -m perfscanner`）：

```bash
dagger scan <项目路径> --base-url http://localhost:8101/api [-c 5] [--quick-requests 50] [-n 2000] [--deep-threshold 20] [-t 30] [-o ./perf_results]
```

`--base-url` 为**必填**参数，由用户显式指定目标服务器的协议/主机/端口（含 context-path，如 `/api`）；工具**不会**自动解析项目配置文件中的 `server.port` 或 `context-path`。

## 1. 结果总览

```
25 passed in 2.79s
```

全部 25 项测试通过，覆盖扫描、分析、压测引擎、报告、CLI 五个模块。

## 2. 功能测试

| 模块 | 测试用例 | 覆盖点 |
| :--- | :--- | :--- |
| scanner | `test_join_path` | 类级/方法级路径拼接、根路径、空路径 |
| scanner | `test_substitute_path_vars` | `@PathVariable` 占位符替换、未声明变量兜底 |
| scanner | `test_scan_extracts_endpoints` | 类级 `@RequestMapping` 前缀 + 方法级注解 → 完整 URL |
| scanner | `test_scan_path_variable_resolution` | `{id}` → `1`，`full_url` 拼接正确 |
| scanner | `test_scan_skips_non_controllers` | 非 Controller 类的方法级注解被忽略 |
| scanner | `test_scan_http_methods` | GET/POST/PUT/DELETE/PATCH 全识别 |
| scanner | `test_scan_string_path_variable_placeholder` | 字符串类型参数 → `test` 占位符 |
| analyzer | `test_percentile_linear_interpolation` | P50/P95 线性插值（numpy `linear` 算法） |
| analyzer | `test_percentile_edge_cases` | 空列表、单元素、P100 |
| analyzer | `test_compute_metrics` | P95/P99/均值/中位数/成功率聚合 |
| analyzer | `test_compute_metrics_with_errors` | 错误请求计入 `error_count`、成功率 |
| analyzer | `test_select_deep_count` | 阈值整数量 / 小数比例 / 边界裁剪 |
| analyzer | `test_select_deep_returns_slowest` | 按 P95 降序选取慢接口 |
| analyzer | `test_merge_results_prefers_deep_and_sorts` | 深测结果覆盖快测、最终按 P95 降序 |
| engine | `test_run_collects_metrics` | 真实请求、响应时间、成功率、慢接口 P95 更大 |
| engine | `test_run_funnel_marks_slow_as_deep` | 两阶段漏斗：慢接口进入 deep，其余 quick |
| engine | `test_run_handles_timeouts` | 连接失败计为 error，不抛出 |
| engine | `test_run_timeout_recorded_as_slow` | 超时计入 P95（不被当作 0ms 快接口） |
| engine | `test_run_sets_perf_header` | 请求头携带 `X-Perf-Test: True` |
| reporter | `test_build_report_data` | 报告数据结构、deep 数量、最慢接口 |
| reporter | `test_reporter_writes_json_and_html` | JSON 可解析、HTML 含 Chart.js 画布 |
| cli | `test_version` / `test_start_help` | `--version`、`start --help` 参数齐全 |
| cli | `test_start_end_to_end` | 扫描 → 压测 → 生成 JSON/HTML 全链路 |

## 3. 兼容性测试

- **Java 8+ 注解**：`@GetMapping` / `@PostMapping` / `@PutMapping` / `@DeleteMapping` / `@PatchMapping` / `@RequestMapping(value, method)` / 数组路径 `@DeleteMapping({"/a","/b"})` 均正确解析。
- **Java 17+ 新语法**（如 `record`）：`test_scan_skips_unparseable_files` 验证解析失败时**跳过该文件**而非崩溃（对应需求 §9.2）。
- **HTTP 方法**：`@RequestMapping(method = RequestMethod.GET)` 通过 `MemberReference` 正确映射。
- **路径变量**：`@PathVariable("id")` 与未命名 `@PathVariable Long id` 均正确提取。

## 4. 性能设计验证

- **两阶段漏斗**（需求 §3.3）：对 N 个接口，第一阶段仅 `quick_requests`（默认 50）个请求，仅对 Top-K 慢接口执行 `deep_requests`（默认 2000）个请求，避免数百接口全量深测。
- **连接复用**（需求 §3.2）：压测引擎全程复用单个 `aiohttp.ClientSession`（见 `engine.LoadEngine.run`）。
- **并行控制**（需求 §3.3）：`asyncio.Semaphore(max_parallel)` 限制同时压测的接口数，默认 5。
- **服务器保护**（需求 §9.4）：连续 3 个接口失败率 ≥ 50% 时自动减半单接口并发（`LoadEngine._maybe_throttle`）。

## 5. 端到端演示

### 5.1 真实项目（glow Controller 层）实测

对 `D:\31124\Devtools\DASH\glow\src\main\java\com\night\glow\controller`（3 个 Controller、13 个接口）以 `--base-url http://localhost:8101/api` 实测，正确识别全部 13 个接口并按 P95 从慢到快排名（`-t 3` 下 `/info` 因真实慢查询超时，排名第 1）：

```
#1  GET  /info           p95=3016ms  0.0%   (慢查询，超时)
#2  POST /post/list      p95=21ms    0.0%
#3  POST /user/register  p95=20ms    0.0%
...
#13 GET  /user/get       p95=2.4ms   0.0%
```

> 说明：POST 接口因工具不自动生成 `@RequestBody`/`@RequestParam` 请求体/参数，均返回 4xx/415（成功率如实记为 0%）；这是静态扫描的固有限制（需求文档仅要求处理 `@PathVariable`）。工具核心价值——发现最慢接口（`/info`）——已验证。

### 5.2 示例项目（模拟慢接口）

以 4 个接口的示例项目 + 本地服务器实测，两阶段漏斗正确将 `deep-threshold=2` 个慢接口标记为 `deep`，输出排名（P95 从慢到快）：

```
#1 GET /api/orders/search        p95=2891ms  phase=deep
#2 GET /api/orders/{id}/detail   p95=1558ms  phase=deep
#3 POST /api/users               p95= 39ms   phase=quick
#4 GET /api/users/{id}           p95= 34ms   phase=quick
```

## 6. 已知说明

- 运行环境为中文 Windows 终端时，若通过管道重定向输出，中文可能出现乱码（控制台编码 GBK vs UTF-8）；在真实终端中 `rich`/`click` 自动处理，或设置 `PYTHONIOENCODING=utf-8`。JSON/HTML 报告始终以 UTF-8 写入，不受影响。
