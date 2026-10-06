"""API 文档的中文说明。

**为什么单独放一个文件**:Swagger 页面上的分组名默认来自 `APIRouter(tags=[...])`,
不写这里就只有光秃秃的英文分组名;每个接口的 summary 若不给,也是从英文函数名
自动生成的(`List Repos`、`Run Skill`…)。这个页面的读者是中文使用者,
所以把这部分文案集中在一处,改起来不用翻十几个路由文件。

注意 `TAGS_METADATA` 的**顺序就是 Swagger 上的分组顺序** ——
按「先看仓库 → 再看具体工作 → 最后是扩展与权限」排,而不是按字母序。
"""

from __future__ import annotations

TAGS_METADATA = [
    {"name": "系统", "description": "健康检查与运行模式。"},
    {"name": "仓库", "description": "仓库列表、健康总览(未处理 Issue / 待 Review PR / 失败 CI 等六项统计)与会话。"},
    {"name": "Issue 分诊", "description": "Issue 列表,带分组计数与状态、负责人、关键词筛选。"},
    {"name": "PR 审查", "description": "PR 列表,标出改动涉及的高风险路径。"},
    {"name": "CI 排障", "description": "CI 运行列表,含结论与耗时。"},
    {"name": "RAG 检索", "description": "混合检索(向量 + 关键词 → RRF 融合 → 重排)与逐阶段的召回测试。"},
    {"name": "SSE 流式对话", "description": "Agent 对话主入口。逐事件推送运行轨迹:上下文、工具调用、草稿、多 Agent 工作流、最终结论。"},
    {"name": "草稿与审计", "description": "写操作一律先生成草稿,**人工确认后**才执行;越权尝试与执行结果都留审计。"},
    {"name": "长期记忆", "description": "会话结束后沉淀记忆候选,**人工批准后**才参与后续召回。"},
    {"name": "运行轨迹", "description": "单次运行的完整轨迹:工具调用、多 Agent 工作流、任务与观察。"},
    {"name": "Agent 评测", "description": "固定评测集 + 硬规则断言 + RAGAS 判分。"},
    {"name": "自动周报", "description": "调度器按周期自动生成周报并回写知识库,也可手动触发(同周期幂等)。"},
    {"name": "Skill 技能", "description": "把稳定的操作流程声明成可复用技能;技能会注册进工具表,Agent 可以直接调用。"},
    {"name": "MCP 外部工具", "description": "通过 MCP 协议接入的外部能力(stdio transport),同样注册进工具表供 Agent 调用。"},
    {"name": "权限与认证", "description": "角色只认请求头或令牌,不接受请求体里的角色 —— 避免越权声明。"},
]

APP_DESCRIPTION = """
DevFlow AI —— 面向研发协作的多 Agent 助手。

### 它能做什么

- **仓库健康 / Issue 分诊 / PR 审查 / CI 排障** —— 四个专用 Agent,各有明确的职责边界
- **RAG 工程化检索** —— 混合召回 + RRF 融合 + 重排,答案带引用;检索不到就明说,不编
- **多 Agent 协作** —— planner 拆解 → 并发执行 → observer 找冲突 → synthesis 综合
- **长期记忆** —— 会话结束沉淀候选,人工批准后才参与召回
- **写操作闸门** —— 所有写操作先生成草稿,人工确认后才执行,越权尝试留审计
- **自动周报 / MCP / Skill** —— 周报自动生成并回写知识库;外部能力经 MCP 与 Skill 注册进工具表
- **SSE 流式** —— 全程逐事件推送运行轨迹,支持取消

### 两种运行模式(在 `.env` 切换,互不混用)

| 变量 | 取值 | 说明 |
|---|---|---|
| `LLM_MODE` | `mock` / `openai` | 前者离线确定性,后者真实模型 |
| `EMBED_MODE` | `mock` / `openai` | 前者假向量,后者真实嵌入 |
| `DATA_SOURCE` | `snapshot` / `github` | 前者内置演示数据,后者真实 GitHub;github 模式下拿不到数据就**如实报错**,不会用快照顶替 |

### 认证

默认 demo 模式(不校验);配置 `DEVFLOW_ROLE_TOKENS` 后进入 enforced,
角色从 `X-DevFlow-Role` 请求头或 Bearer 令牌解析 —— **不接受请求体里的角色**。
"""
