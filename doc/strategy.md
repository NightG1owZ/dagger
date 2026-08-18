# 压测失败请求处理策略（Strategy）

> 适用范围：`dagger scan` / `perf-tool`（PerfScanner）——扫描 Java Controller 接口并做并发压测、按 P95/P99 排序。
>
> 本文声明工具在**压测过程中遇到失败请求时如何统计**，以及为什么这样统计，避免失败请求污染 P95/P99 排名。

---

## 目录

1. [问题本质](#1-问题本质)
2. [统计口径：分层统计（默认策略）](#2-统计口径分层统计默认策略)
3. [请求分类规则](#3-请求分类规则)
4. [质量门禁（Quality Gate）](#4-质量门禁quality-gate)
5. [排名规则](#5-排名规则)
6. [报告字段](#6-报告字段)
7. [辅助措施](#7-辅助措施)
8. [测试用例](#8-测试用例)
9. [结论](#9-结论)

---

## 1. 问题本质

P95/P99 的语义是「**一个正常请求，在绝大多数情况下最慢会慢到什么程度**」。它的前提是：被统计的样本必须来自**同一个统计总体**——即「系统成功处理请求」这一过程。

一旦把失败请求混入，样本就来自多个总体：

| 失败类型 | 典型延迟 | 对 P95/P99 的污染方向 |
| :--- | :--- | :--- |
| 快速失败（参数校验 400、认证拒绝 401/403） | 毫秒级 | **拉低**分位数，掩盖真实慢接口 |
| 慢失败（超时、慢 5xx） | 接近/等于超时阈值 | **拉高**分位数，误判为性能差 |
| 两者并存 | 分布呈双峰 | 分位数在峰间跳变，**结果不可复现** |

结论：失败请求与成功请求是**不同维度**的度量。失败回答的是「系统会不会失败、失败得多快」，不能强行折算进「正常请求有多慢」。

### 工具构造问题 vs 系统自身问题

| 类别 | 定义 | 典型表现 | 处理 |
| :--- | :--- | :--- | :--- |
| **工具构造问题**（Harness） | 请求本身是错的，系统正确地拒绝了它 | 连接被拒/DNS/TLS、缺参数、缺认证 | **剔除**，不计入任何性能指标，提示修复 |
| **系统自身问题**（System） | 请求合法，但系统无法正常处理 | 5xx、429 限流、业务 4xx、超时 | **如实统计**，进入错误率与失败分布 |

---

## 2. 统计口径：分层统计（默认策略）

> **默认方案 =「分层统计 + 成功请求计算主分位数 + 错误率作为一等指标」。**

- **排名主键**：成功请求的 P95/P99（保证「性能」口径纯净）。
- **稳定性指标**：每个接口同时携带**错误率**与**失败分布**（5xx/4xx/超时分别计数），错误率与性能并列展示，杜绝幸存者偏差。
- **工具错误**：自动识别为 `HARNESS_ERROR`，从性能与错误率中剔除，并单独计数告警。

**被否决的两种方案及原因：**

| 方案 | 缺陷 |
| :--- | :--- |
| 仅统计成功请求（不报错误率） | 幸存者偏差：并发越高、失败越多、成功样本越「顺」，P95/P99 反而越好看 |
| 失败请求一律计为超时 | 惩罚值是人为设定，P95/P99 变成合成指标，与超时阈值强耦合，不可跨轮对比 |

---

## 3. 请求分类规则

每个请求在结束时被归入**互斥**的五个类别之一（实现见 `perfscanner/analyzer.py::classify_request`）：

| 类别 | 判定规则 | 归属 | 统计处理 |
| :--- | :--- | :--- | :--- |
| `SUCCESS` | 状态码 2xx/3xx | 系统 | 进入**主延迟分布**，参与 P95/P99 排名 |
| `CLIENT_ERROR` | 4xx 且请求构造正确（业务拒绝：权限不足、数据不存在等） | 系统 | 计入错误率，独立计数 |
| `SERVER_ERROR` | 5xx | 系统 | 计入错误率，独立计数 |
| `TIMEOUT` | 超过超时阈值（`asyncio.TimeoutError` 或响应晚于 deadline） | 系统 | 计入错误率，独立计数 |
| `HARNESS_ERROR` | 传输层错误（`aiohttp.ClientConnectionError` 等） | 工具 | **剔除**，不计入性能与错误率，单独计数 |

判定顺序（代码中严格遵循）：

1. 传输层异常 → `HARNESS_ERROR`
2. 超时异常 → `TIMEOUT`
3. 无状态码且非上述异常 → `HARNESS_ERROR`
4. 响应晚于 deadline → `TIMEOUT`
5. 2xx/3xx → `SUCCESS`
6. 5xx → `SERVER_ERROR`
7. 4xx 且工具确认构造错误 → `HARNESS_ERROR`
8. 其余 4xx → `CLIENT_ERROR`

### 错误率口径

```
有效请求数 = 总请求数 − HARNESS_ERROR 数
错误率     = (SERVER_ERROR + CLIENT_ERROR + TIMEOUT) / 有效请求数 × 100%
成功率     = SUCCESS / 有效请求数 × 100%
```

> 注意：`HARNESS_ERROR` 不进分母——工具自身请求没发对，不应算作系统的「失败」。

---

## 4. 质量门禁（Quality Gate）

| 判定 | 标签 | 展示 |
| :--- | :--- | :--- |
| `error_rate ≤ 1%` 且有成功请求 | `ok` | 🟢 正常 |
| `1% < error_rate ≤ 5%` | `warn` | 🟡 警告 |
| `error_rate > 5%` 或 无成功请求 | `critical` | 🔴 异常 |

阈值常量见 `perfscanner/analyzer.py::WARN_ERROR_RATE / CRITICAL_ERROR_RATE`。

---

## 5. 排名规则

最终列表排序（实现见 `perfscanner/analyzer.py::rank_key`）：

1. **无成功请求的接口排在最前**——它们是最严重的故障，绝不能因 `P95 = 0` 被误判为「最快」。
2. 其余接口按**成功请求 P95 降序**（慢 → 快）。

终端与 HTML 表格中，无成功请求的接口 P95/P99 显示为 `N/A`，并带 🔴 标记。

---

## 6. 报告字段

### 6.1 接口明细（`report_data.json` 的 `endpoints[]`）

| 字段 | 说明 |
| :--- | :--- |
| `p95_ms` / `p99_ms` | **成功请求**的 P95/P99（主排序键；无成功时为 `0.0`，前端显示 `N/A`） |
| `mean_ms` / `median_ms` / `min_ms` / `max_ms` | 成功请求的均值/中位数/最小/最大 |
| `success_rate` / `error_rate` | 成功率 / 错误率（0..100，均按有效请求计算） |
| `success_count` | 成功请求数 |
| `server_errors` / `client_errors` / `timeouts` / `harness_errors` | 四类失败分别计数 |
| `retries` | 重试总次数（重试本身不计入成功率/错误率分母） |
| `dropped` | 是否因失败率达标而被中途丢弃（`true`/`false`） |
| `status_codes` | HTTP 状态码分布 |
| `quality` | `ok` / `warn` / `critical` |
| `requests` / `phase` | 总请求数 / 阶段（quick | deep） |

### 6.2 汇总

| 字段 | 说明 |
| :--- | :--- |
| `total_endpoints` | 接口总数 |
| `slowest_endpoint` | 有成功请求的接口中最慢者 |
| `average_p95_ms` | 有成功请求接口的平均 P95（剔除 `N/A`） |
| `unstable_endpoints` | `quality != ok` 的接口数 |
| `critical_endpoints` | `quality == critical` 的接口数 |

---

## 7. 辅助措施

| 措施 | 状态 | 说明 |
| :--- | :--- | :--- |
| 预热（Warm-up） | ✅ 已实现 | 压测前对每个接口发 1 次探测请求，触发 JIT/连接池/缓存，消除冷启动毛刺；结果不计入统计 |
| 请求分类 + 分层统计 | ✅ 已实现 | 本文核心 |
| 质量门禁 | ✅ 已实现 | 错误率阈值打标 |
| 失败重试 | ✅ 已实现 | 传输错误/超时按 `--max-retries` 重试，见 [第 7.1 节](#71-重试策略) |
| 失败丢弃（熔断） | ✅ 已实现 | 失败率达阈值后丢弃接口，见 [第 7.2 节](#72-丢弃策略) |
| 参数/认证构造 | ⏳ 后续 | 支持按接口配置参数、类型感知自动生成、动态获取 token |
| HDR Histogram / t-digest | ⏳ 后续 | 高并发下恒定内存高精度分位数 |
| 开环恒定到达率 | ⏳ 后续 | 规避 coordinated omission（闭环模式低估 P99） |

### 7.1 重试策略

> CLI：`--max-retries N`（默认 `3`）。实现见 `perfscanner/engine.py::_request_with_retry`。

**重试范围——只重试「未收到 HTTP 响应」的请求**：

| 失败类型 | 是否重试 | 原因 |
| :--- | :--- | :--- |
| 传输错误（连接被拒/重置、DNS、TLS）`HARNESS_ERROR` | ✅ 重试 | 瞬时环境噪声，重试可能成功 |
| 超时 `TIMEOUT` | ✅ 重试 | 未收到响应，可能是瞬时抖动 |
| 4xx（参数校验/业务拒绝）`CLIENT_ERROR` | ❌ 不重试 | 确定性的服务器响应，重试结果相同 |
| 5xx `SERVER_ERROR` | ❌ 不重试 | 已收到响应；重试会加倍负载、放大过载 |

**口径**：一次逻辑请求 = 1 次初始尝试 + 最多 `N` 次重试，共 `1 + N` 次 HTTP 尝试。**只有最终结果**进入分类统计；重试次数单独记入 `retry_count`，不计入成功率/错误率分母。

### 7.2 丢弃策略（熔断）

> CLI：`--drop-failure-rate RATE`（默认 `0.5`，>1 禁用）、`--min-requests-before-drop N`（默认 `10`）。实现见 `perfscanner/engine.py::_test_endpoint`。

- 某接口**完成的逻辑请求**（`completed`）达到 `--min-requests-before-drop` 后，若**最终失败率**（非 `SUCCESS` 占比）≥ `--drop-failure-rate`，立即停止该接口的后续请求。
- 已发出但尚未完成的在途请求正常结算；被跳过的请求不再计数。
- 被丢弃的接口在报告中 `dropped: true`，终端/HTML 标记「已丢弃」；其性能数值仅基于已完成的样本，仅供参考。
- 目的：避免对一个持续失败的接口浪费数千次深测请求，同时快速把故障接口暴露给用户。

---

## 8. 测试用例

> 测试目录：`tests/`，运行：`.venv\Scripts\python.exe -m pytest -q`（pytest 9.1.1 + pytest-asyncio）。

### 8.1 分类单元测试（`tests/test_analyzer.py`）

| 用例 | 验证点 |
| :--- | :--- |
| `test_classify_success` | 2xx 与 3xx → `SUCCESS` |
| `test_classify_server_and_client_errors` | 5xx → `SERVER_ERROR`；404 → `CLIENT_ERROR` |
| `test_classify_timeout_via_flag_and_elapsed` | 超时异常 → `TIMEOUT`；响应晚于 deadline → `TIMEOUT`（不当作成功） |
| `test_classify_transport_and_harness_errors` | 传输错误 → `HARNESS_ERROR`；工具已知缺参/缺认证的 4xx → `HARNESS_ERROR` |

### 8.2 分层统计单元测试（`tests/test_analyzer.py`）

| 用例 | 验证点 |
| :--- | :--- |
| `test_compute_metrics_success_only_percentiles` | 全成功时 P95/P99/均值与成功率正确，`quality == ok` |
| `test_compute_metrics_excludes_failures_from_percentiles` | 快速 400（毫秒级）与慢超时（5s）**均不进入** P95——P95 仅由成功样本 [0.4s, 0.5s] 算出 `0.495`；错误率 = 60% |
| `test_compute_metrics_harness_errors_excluded_from_rates` | 连接错误从分母剔除：2 成功 + 1 harness → 成功率 100%、错误率 0% |
| `test_compute_metrics_no_success_is_critical` | 全 5xx → P95=0、错误率 100%、`quality == critical` |
| `test_quality_flag_thresholds` | 1%/5% 阈值边界；无成功请求恒为 `critical` |
| `test_status_codes_preserved` | 状态码分布保留 |

### 8.3 引擎集成测试（`tests/test_engine.py`）

| 用例 | 验证点 |
| :--- | :--- |
| `test_run_collects_metrics` | 全成功接口：错误率 0%、`quality == ok`、慢接口 P95 更大 |
| `test_run_connection_error_is_harness_error` | 连接错误（端口 0）→ `harness_error_count == 5`，且**不**计入 `error_count`/`error_rate` |
| `test_run_timeout_counted_separately` | 超时 → `timeout_count == 5`、P95=0（无成功样本）、`quality == critical` |
| `test_run_http_errors_classified_and_excluded_from_p95` | 快速 400 接口：`client_error_count == 20`、`P95 == 0`（不被误判为「快」）；500 接口：`server_error_count == 20`；正常接口 P95 不受影响 |
| `test_run_retries_transient_timeout_then_succeeds` | 超时请求按 `max_retries` 重试后成功：`success_count == 1`、`retry_count == 2`、`timeout_count == 0` |
| `test_run_does_not_retry_http_errors` | 4xx 是确定性响应，不重试：5 个逻辑请求 = 5 次 HTTP 尝试，`retry_count == 0` |
| `test_run_drops_endpoint_on_high_failure_rate` | 持续 500：达到阈值后 `dropped == true`，实际完成请求数远小于 `n` |
| `test_run_does_not_drop_healthy_endpoint` | 全成功接口：`dropped == false`，`count == n` |
| `test_run_funnel_marks_slow_as_deep` | 两阶段漏斗：慢接口进 deep，最终慢者排前 |

### 8.4 报告测试（`tests/test_reporter.py`）

| 用例 | 验证点 |
| :--- | :--- |
| `test_build_report_data` | 报告含 `error_rate`/`quality`；`unstable_endpoints` 正确 |
| `test_build_report_data_flags_unstable` | 无成功接口排最前、`critical_endpoints == 1`；`slowest_endpoint` 只从有成功的接口中取 |
| `test_reporter_writes_json_and_html` | JSON/HTML 产物生成且含新字段 |

### 8.5 关键场景对照表

| 场景 | 期望结果 |
| :--- | :--- |
| 接口 100% 快速 400（参数校验失败） | 不计入 P95；`client_error_count` 高、错误率 100%、🔴；P95 显示 `N/A`，不排「最快」 |
| 接口 100% 超时 | 不计入 P95；`timeout_count` 高、🔴；P95 显示 `N/A`，排最前 |
| 接口混合「3ms 失败 + 200ms 成功」 | P95 ≈ 成功样本分位（不受 3ms 失败拉低） |
| 目标地址写错（连接被拒） | `harness_error_count` 高，`error_rate` 为 0%（工具错误不算法系统失败），提示修复 |
| 接口偶发超时后恢复 | 超时按 `--max-retries` 重试，最终成功则计为成功，`retry_count` 记录重试数 |
| 接口持续 500/超时 | 达到 `--drop-failure-rate` 后 `dropped=true`，提前结束压测并标记「已丢弃」 |

---

## 9. 结论

把「性能」与「稳定性」作为两个正交维度分开测量：

- **成功请求的 P95/P99** 度量性能（排名主键）；
- **错误率 + 失败分布**（5xx/4xx/超时分别计数）度量稳定性；
- **工具自身错误**（`HARNESS_ERROR`）修复后重测，系统真实失败如实呈现——**既不混入，也不丢弃**。

相关实现文件：

- `perfscanner/models.py` — `RequestCategory` / `RequestSample` / `EndpointMetrics` 分层字段
- `perfscanner/analyzer.py` — `classify_request` / `compute_metrics` / `quality_flag` / `rank_key`
- `perfscanner/engine.py` — 请求分类采集 + 预热
- `perfscanner/reporter.py` — 报告字段
- `perfscanner/core.py` — 终端排行表（错误率/质量列）
- `perfscanner/templates/report.html` — HTML 报告（错误率/质量列）
