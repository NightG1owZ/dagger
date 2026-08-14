# 插件系统

Dagger 提供可扩展的插件机制，在压测生命周期中注入自定义行为。

## 发现机制

插件通过 `setuptools` 的 `entry_points`（组名 `dagger.plugins`）自动发现，也可通过 `--plugin-dir` 指定额外目录。

## 内置插件

| 插件 | 名称 | 说明 |
| :--- | :--- | :--- |
| Bearer 自动刷新 | `auth_bearer` | 长时压测中自动刷新 Bearer Token |
| 请求记录 | `request_recorder` | 将每次请求/响应元数据落盘，便于调试与回放 |

### 查看插件

```bash
dagger plugins list
dagger plugins info auth_bearer
```

---

## 1. auth_bearer（Bearer Token 自动刷新）

在请求发出前注入 `Authorization: Bearer <token>`，并在 token 过期前自动刷新。

配置（`dagger.yaml`）：

```yaml
plugins:
  auth_bearer:
    token_endpoint: "https://auth.example.com/oauth/token"
    client_id: "my-client"
    client_secret: "my-secret"
    refresh_interval: "300s"     # 可选，默认 300s
```

- 通过 `client_credentials` 授权模式从 `token_endpoint` 换取 `access_token`。
- 每次 `pre_request` 检查 token 是否过期，过期则刷新。

---

## 2. request_recorder（请求记录）

将每次请求的结果记录到磁盘，用于后续分析。

配置（`dagger.yaml`）：

```yaml
plugins:
  request_recorder:
    enabled: true                 # 可选，默认 true
    output_dir: "./request_logs"  # 可选
    max_records: 10000            # 可选，默认 10000
```

测试结束后写入 `request_logs/request_log.json`，每条记录含：时间戳、延迟、状态码、响应大小、错误信息、虚拟用户 ID、请求序号。

---

## 插件生命周期钩子

插件继承 `DaggerPlugin`，覆写以下钩子方法：

| 钩子 | 触发时机 | 签名 |
| :--- | :--- | :--- |
| `on_configure` | 插件配置加载时 | `(config: dict)` |
| `pre_request` | 请求发送前（可修改 TargetSpec） | `(target) -> target` |
| `post_response` | 请求完成后 | `(result) -> result` |
| `on_error` | 请求出错时 | `(result, exception)` |
| `on_test_start` | 测试开始时 | `(session)` |
| `on_test_end` | 测试结束时 | `(summary)` |
| `on_metric_tick` | 每次实时指标刷新时 | `(snapshot)` |

## 编写自定义插件

### 1. 定义插件类

```python
# my_plugin.py
from dagger.plugins.base import DaggerPlugin


class UserAgentPlugin(DaggerPlugin):
    name = "user_agent"
    version = "1.0.0"
    description = "为每个请求附加自定义 User-Agent"

    def __init__(self):
        self._ua = "dagger-custom/1.0"

    async def pre_request(self, target):
        target.headers["User-Agent"] = self._ua
        return target
```

### 2. 注册 entry_point

在 `pyproject.toml` 中注册：

```toml
[project.entry-points."dagger.plugins"]
user_agent = "my_plugin:UserAgentPlugin"
```

或使用 `--plugin-dir` 指定插件目录：

```bash
dagger run -u https://api.example.com -c 10 -d 30s --plugin-dir ./my_plugins
```

### 3. 在配置中启用

```yaml
plugins:
  user_agent:
    # 自定义配置（传给 on_configure）
```

---

## 说明

- 钩子调用失败会被捕获并记录日志，不会中断压测主流程。
- `pre_request` 类钩子（返回修改后的对象）会按插件顺序链式传递。
- 插件通过 `asyncio` 异步调用，不会阻塞压测协程。
