# OpenAPI 压测工具（`java/`）

针对 **Java Spring** 服务的压测工具：用户提供运行中服务的 **OpenAPI（Swagger）文档 URL**
（如 `http://localhost:8101/api/v3/api-docs`），工具自动完成：

1. **解析** OpenAPI 文档中的所有接口（路径、HTTP 方法、Query / Path / Header 参数、JSON 请求体 Schema）。
2. **生成** 符合 Schema 约束的测试数据（string / integer / number / boolean / array / object、`$ref`、`enum`、`format`、`minLength` / `maxLength`、`minimum` / `maximum` 等）。
3. **冒烟预检**：每个接口先发一次请求，判定是否可压测（HTTP 2xx，且 JSON 响应中若有业务 `code` 字段须为 `0` 或 `200`）。
4. **压力测试**：对可压测的接口用 `asyncio + aiohttp` 并发压测（按请求总数或时长）。
5. **报告**：输出全部接口的 P95 / P99 列表，**按 P95 从高到低排序**，标明因业务错误未能正确压测的接口。

本目录按"一个语言一个文件夹"的规划自包含全部功能；后续其他语言（Python / Go 等）的压测工具
可建平级目录。运行方式：

```bash
# 从仓库根目录
python -m java --openapi-url http://localhost:8101/api/v3/api-docs
```

## CLI 参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--openapi-url` | （必填） | OpenAPI 文档 URL，如 `http://localhost:8101/api/v3/api-docs` |
| `--concurrency` | 10 | 每个接口的并发协程数 |
| `--total-requests` | 1000 | 每个接口的总请求数（指定 `--duration` 时忽略） |
| `--duration` | 无 | 每个接口的压测时长（秒），指定后忽略 `--total-requests` |
| `--output` | 无 | 报告文件路径（`.json` 或 `.csv`），默认仅打印到控制台 |
| `--skip-error-apis` | False | 启用后跳过冒烟测试失败的接口，只压测通过冒烟的接口 |
| `--base-url` | 无 | 覆盖 OpenAPI `servers` 字段的 base URL |
| `--timeout` | 10 | 单次请求超时（秒），超时计为失败且**不重试** |
| `--drop-failure-rate` | 0.5 | 压测中失败率达到该阈值（0~1）后**丢弃此接口**并停止继续请求；设为大于 1 可禁用丢弃 |
| `--min-requests-before-drop` | 10 | 至少完成多少请求后才允许触发丢弃 |
| `--verbose` | False | 输出调试日志 |

示例：

```bash
python -m java --openapi-url http://localhost:8101/api/v3/api-docs \
    --concurrency 20 --total-requests 500 --skip-error-apis \
    --output ./results/report.json
```

## 工作流程

1. **获取并解析** OpenAPI JSON（仅支持 OpenAPI 3.x；`$ref` 仅支持本地
   `#/components/...` 引用，`allOf` 会合并）。base URL 取 `servers[0].url`，可用
   `--base-url` 覆盖。
2. **数据生成**：请求体、Query / Path / Header 参数均按 Schema 生成，保证：
   - **必填字段强制生成**：`required` 数组中的字段必定生成，且**非空**（空值会重试，
     仍为空则按类型回退，如字符串回退为随机串、整数回退为 `1`）；非必填字段按 **50%**
     概率随机生成（模拟真实请求的字段差异）。
   - **请求体永不为空**：只要 Schema 声明了 `properties`，请求体就不会是 `{}`——
     所有可选字段都"未命中"时会重新生成，最终兜底包含第一个声明字段。
   - **类型映射**：`string + email` → faker 的 `email()`；`string + date-time` →
     `datetime.now().isoformat()`；普通 string 按 `minLength`/`maxLength` 生成随机串；
     `integer`/`number` 在 `minimum`/`maximum` 内随机；`boolean` 随机。
   - **业务唯一字段防冲突**：字段名含 username / email / slug / login / account 等
     唯一性提示时，值后追加 UUID 后缀（如 `user_ab12cd34`），万次压测不冲突；
     Path / Query / Header 参数同样适用。
   - **嵌套递归**：`object` 递归生成（必填子字段非空），`array` 生成 1~3 个元素。
   - Path 参数（如 `/user/{id}`）按 Schema 生成（integer → `1` 附近，string → 满足
     长度约束的随机串）；Schema 缺失时预置为 `1`。未解析的 `{占位符}` 一律替换为 `1`。
3. **冒烟预检**：单请求判定每个接口是否可压测。
   - **通过**：HTTP 2xx，且响应为 JSON 且含 `code` 字段时 `code ∈ {0, 200}`。
   - **失败**：记录原因（`HTTP 400: ...`、`业务码 500: ...`、`请求超时(>10s)`、
     `连接失败: ...`），该接口标记为"失败"；`--skip-error-apis` 时跳过压测（"跳过"）。
4. **压力测试**：接口**逐个**压测，每个接口内部按 `--concurrency` 并发；请求数或时长
   按参数决定。
   - **成功判定与冒烟一致**：HTTP 2xx **且**（若响应为 JSON 且含 `code` 字段）业务码
     `∈ {0, 200}`。HTTP 2xx 但业务码报错（如 `{"code":50000,"message":"系统错误"}`、
     `{"code":50000,"message":"用户 ID 不能为空"}`）记为**失败**，否则这类接口会被
     一直压测却显示 100% 成功。
   - 重试：仅**连接类错误**（连接被拒 / 重置 / DNS / TLS，即未收到任何响应）重试，
     最多 **2 次**；超时、4xx/5xx 与业务码失败均为确定性失败，**不重试**。
   - 计时从发送到收到完整响应；**只有成功响应**进入百分位计算，连接错误、超时、
     4xx/5xx、业务码失败都记为失败并从百分位中排除。
   - **丢弃策略**：完成 `--min-requests-before-drop`（默认 10）个请求后，若失败率
     ≥ `--drop-failure-rate`（默认 0.5），立即停止该接口的后续请求并标记 **"已丢弃"**
     ——避免对持续失败（如冒烟已失败、业务码恒报错）的接口空耗请求。`--drop-failure-rate`
     设为大于 1 可禁用。
5. **统计与报告**：
   - P95 / P99 按需求指定的索引公式计算：`sorted[int(0.95 * len)]` /
     `sorted[int(0.99 * len)]`。
   - 有效（成功）样本 **少于 10 个** 时标记为 **"数据不足"**，P95/P99 显示为 `—`。
   - 状态：`成功` / `数据不足` / `失败` / `跳过`；按 P95 降序排列，无 P95 的接口排最后；
     被丢弃的接口在"说明"列显示"已丢弃(失败率过高)"。

## 输出报告

- **控制台**：`rich` 表格，列为 排名 / 接口 / 状态 / P95(ms) / P99(ms) / 请求数 / 成功 / 失败 / 说明。
- **JSON**（`--output x.json`）：`{base_url, total, endpoints: [...]}`，每条含
  `method / path / status / p95_ms / p99_ms / requests / success / failed / retries / dropped / reason`。
- **CSV**（`--output x.csv`）：同上字段，UTF-8 BOM 编码（Excel 可直接打开）。

## 设计说明与限制

- **认证**：工具不配置认证信息；需要登录 token 的接口会在冒烟阶段因 401/403 被标记
  为失败。可将需要放行的接口部署在独立测试环境后压测。
- **依赖链（进阶，未实现）**：需要"先创建后使用"的接口（如先 POST 注册拿到 id 再
  GET `/user/{id}`），本版未实现前置请求 / 依赖注入，Path 参数按 Schema 预置数据
  （缺省为 `1`）。后续可通过 YAML 前置请求配置或按 `operationId`（如 `create` /
  `delete`）自动推断实现。
- **数据清理**：压测会产生测试数据，建议在**独立测试环境**执行；工具不自动清理，
  也不会删除任何数据。
- **OpenAPI 版本**：仅支持 OpenAPI 3.x（`components.schemas`、`requestBody.content`）。
  Swagger 2.0（`definitions`、`body` 参数）不在支持范围。
- **业务码约定**：冒烟与压测阶段均检查 JSON 顶层 `code` 字段（`0` / `200` 视为成功）；
  若接口不使用该字段则只看 HTTP 状态码。业务码失败是**确定性**失败（不重试），
  并计入失败率参与丢弃判定。

## 测试

```bash
.\.venv\Scripts\python.exe -m pytest java\tests -q
```

覆盖：OpenAPI 解析（`$ref`、`allOf`、servers / base-url）、数据生成（类型 / 约束 /
format）、P95/P99 索引公式与"数据不足"、冒烟判定（HTTP / 业务码 / 超时 / 连接失败）、
引擎（请求数 / 时长模式、连接错误重试 ≤ 2、超时与 HTTP 错误不重试、成功样本才计百分位）、
报告输出（JSON / CSV / 控制台）以及 CLI 端到端。
