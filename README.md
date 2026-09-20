# HireAgent

企业智能化解决方案团队基于统一 Agent 交付底座，为招聘协作场景完成的脱敏参考实现。项目将候选人档案、岗位匹配、面试排期封装成 **13 个可调用工具**，由 **3 个职责受限的本地 Agent** 处理 **9 类结构化意图**，同时通过 FastMCP 与 FastAPI 提供 MCP、JSON API 和 SSE 接口。

当前公开版本使用规则路由、可解释评分和内存存储，可以离线运行；已实现 FastMCP STDIO 与 Streamable HTTP 传输，尚未接入客户招聘系统、LLM 或 A2A 网络协议。示例数据均为合成数据。平台复用和行业适配边界见 [REUSE_MAP.md](docs/REUSE_MAP.md)。

## 快速运行

需要 Python 3.11 或更高版本。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn hire_agent.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Linux/macOS 使用 `source .venv/bin/activate` 激活环境，其余命令相同。

打开 [接口文档](http://127.0.0.1:8000/docs)。默认载入 `demo-c1`、`demo-c2` 两个候选人以及 `demo-j1` 一个岗位；`GET /tools` 返回所有工具的参数 JSON Schema。

PowerShell 调用匹配工作流：

```powershell
$body = @{
    intent = "candidate_match"
    arguments = @{ candidate_id = "demo-c1"; job_id = "demo-j1" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/workflows" -ContentType "application/json" -Body $body
```

返回候选人技能交集、缺失技能、经验差距、地点匹配、总分以及跨 Agent 的工具执行轨迹。演示候选人甲对演示岗位得分为 100，乙为 33.33。评分只使用输入的技能、工作经验和地点，不包含年龄、性别等个人属性；它是规则演示，不是录用决策。

无需启动 HTTP 服务也可运行：

```powershell
python examples/demo.py
python examples/evaluate.py
python -m pytest
```

## MCP Server

默认使用 STDIO，适合由桌面 Agent 客户端按需启动：

```powershell
python -m hire_agent.mcp_server
```

客户端配置示例：

```json
{
  "mcpServers": {
    "hireagent": {
      "command": "python",
      "args": ["-m", "hire_agent.mcp_server"]
    }
  }
}
```

启动 Streamable HTTP 服务：

```powershell
python -m hire_agent.mcp_server --transport http --host 127.0.0.1 --port 8001
```

MCP Endpoint 为 `http://127.0.0.1:8001/mcp`。13 个 MCP Tool 与 HTTP API 复用同一套 Pydantic 参数模型、领域校验、锁和幂等状态，不维护第二套业务逻辑。

独立拉起服务并执行一次真实 HTTP 协议往返：

```powershell
python examples/mcp_http_smoke.py
```

## 9 类意图与 13 个工具

| Agent | 意图 | 主工具 |
| --- | --- | --- |
| ResumeAgent | `candidate_upsert` | `upsert_candidate` |
| ResumeAgent | `candidate_search` | `search_candidates` |
| ResumeAgent | `candidate_summary` | `summarize_resume` |
| JobAgent | `job_upsert` | `upsert_job` |
| JobAgent | `job_search` | `search_jobs` |
| JobAgent | `candidate_match` | `match_candidate` |
| InterviewAgent | `interview_slots` | `list_interview_slots` |
| InterviewAgent | `interview_schedule` | `schedule_interview` |
| InterviewAgent | `interview_cancel` | `cancel_interview` |

另外四个工具为 `get_candidate`、`get_job`、`rank_candidates`、`list_interviews`。所有工具都可以通过 `POST /tools/{tool_name}` 单独调用。匹配工作流依次读取候选人、读取岗位、计算匹配结果；其他意图直接调用相应职责 Agent。

调用者明确提供 `intent` 和 `arguments`，本版本不从自由文本推断意图。`summarize_resume` 根据结构化档案生成事实模板摘要，不负责 PDF/Word 简历解析。工具参数由 Pydantic 校验，未知字段、错误类型和缺少必填字段会得到 422。

匹配评分：技能覆盖率 × 70 + 经验达标比例 × 20 + 地点兼容 × 10。工作经验得分上限为 20；远程岗位视为地点兼容；技能进行去重及大小写归一化，未实现同义词或向量语义匹配。

## 排期、冲突与幂等

`schedule_interview` 要求 `candidate_id`、`job_id`、`interviewer_id`、带时区的 `starts_at`、`duration_minutes`（15–120）和 `idempotency_key`。

- 校验候选人与岗位存在，开始时间必须在未来；接受任意未来时段，不强制要求来自建议时段列表。
- 候选人或面试官任一方存在重叠排期时返回 409；前一场结束与下一场开始相同允许预约。
- 同一幂等键、相同请求返回同一预约；相同键配不同参数返回 409。等价的时区表示会归一化后比较。
- 取消操作可重复调用，取消后释放时段。旧预约键重试会返回已取消记录；重新预约需使用新键。
- `list_interview_slots` 返回 UTC 周一至周五 09:00–17:00 内每小时起始的建议时段，排除该面试官已占用时间。它不是实际日历服务，也不检查具体候选人的占用；预约时再检查双方。

内存仓库使用同一个可重入锁保护排期冲突检查与写入，测试覆盖并发重复请求和竞争预约。幂等记录与排期只在当前进程内有效，服务重启即清空。

## API 与 SSE

| 路径 | 用途 |
| --- | --- |
| `GET /health` | 健康状态与存储类型 |
| `GET /agents` | Agent 工具权限和意图清单 |
| `GET /tools` | 13 个工具与参数 Schema |
| `POST /tools/{tool_name}` | 执行单个工具 |
| `POST /workflows` | 同步执行意图工作流 |
| `POST /workflows/stream` | 以 SSE 返回工作流过程 |

SSE 请求体与 `/workflows` 相同。事件顺序为 `routed → tool_started → tool_completed → … → completed`；运行时领域错误以终止 `error` 事件返回，不再发送 `completed`。参数错误在响应头发送之前返回 HTTP 422；已经开始的流出现业务错误时 HTTP 状态仍为 200，客户端必须检查事件类型。它是工具进度事件流，不是大模型 Token 流。

这是 POST 接口，浏览器客户端需通过 `fetch` 读取流，不能直接使用只支持 GET 的原生 `EventSource`。流中断不撤销已发生的写入；排期重试应复用原幂等键。

## 目录与验证

```text
src/hire_agent/
  domain.py     输入与领域模型
  store.py      内存仓库及合成示例
  tools.py      工具注册、评分、排期与并发保护
  agents.py     意图路由、职责限制与工作流事件
  mcp_server.py FastMCP STDIO 与 Streamable HTTP 协议适配
  api.py        FastAPI / SSE
tests/          工具、并发、幂等、工作流与 HTTP 回归测试
examples/       无外部服务的运行示例
docs/           复用边界说明
```

测试覆盖 13 个工具的实际调用、评分明细、候选人与面试官冲突、跨时区幂等、并发预约、取消重试、Agent 工具权限、API 校验、SSE 终止事件，以及 MCP Tool Discovery、Schema、调用和幂等行为。

## Agent 评测口径

`examples/evaluate.py` 使用合成回归样例输出两层指标，不把测试结果冒充生产指标：

- 步骤级：根据 `tool_started` 与 `tool_completed` 事件计算工具调用成功率。
- 端到端：执行前后对候选人、岗位、面试和幂等状态做字段级快照，对比“应变化字段”“实际变化字段”“不应变化字段”。只有结果正确、目标字段变化且没有额外字段被修改，任务才算成功。

当前内置 3 个确定性样例用于证明评测方法可运行；样例数量和结果不代表线上业务效果。

## 当前边界

仅供本机、单进程演示，默认无认证、权限隔离或持久化，请将 HTTP 服务绑定到 `127.0.0.1`，并使用一个 worker。多 worker 或多实例之间不共享排期及幂等状态。不提供邮件发送、外部日历、附件上传、真实招聘数据接入或线上性能指标。

`.env.example` 只是配置示例，程序不自动读取 `.env`。若要关闭 HTTP API 的合成数据，在启动前设置 PowerShell 环境变量 `$env:HIREAGENT_DEMO_DATA = "false"`。后续接入数据库时，需要用数据库事务与唯一约束代替当前进程锁；A2A、LLM、认证和持久化适配尚未实现。
