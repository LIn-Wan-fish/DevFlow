# DevFlow AI Demo 设计:多智能体研发协作助手(端到端最小闭环)

> 参考来源:公众号「小林coding」《面试官质疑:"你的Agent项目,不就是套了个 API?"》(<https://mp.weixin.qq.com/s/S4Hnz3W8Hs3TR0rA1odV1w>)
> 原文归档与图片见 `docs/refs/`。本文不是课程文档的搬运,而是把原文描述的 DevFlow AI 拆成一个**可运行、可验收的最小闭环**。
>
> **实施状态(2026-10-05)**:本文描述的设计**已全部实现并验收通过** —— 后端 216 个单测、前端 23 个单测全绿,真实 PostgreSQL + Milvus 容器下全链路 HTTP 验收 FAIL=0(PASS 48~49,其中一条负向断言在已有生效记忆时按设计跳过)(mock 与真实模型两种模式均为 0 失败)。使用说明见 [`操作手册.md`](操作手册.md)。
> 实际实现与本文/Plan 的差异(含只有跑真实环境才暴露的中文关键词召回失效等问题)**集中记录在 `docs/Plan-DevFlow-AI-Demo.md` 末尾的「实施记录」一节**。
> 其中一条需要特别说明:后端实际运行在 `python:3.12-slim` 容器内,宿主 3.14 未参与,与最初选的「用本机 3.14」不一致。

## 目标

把「研发协作助手」这条链路真正跑通,而不是套一层聊天壳。

用户在一个工作台里选中仓库/会话,提一个研发问题(「这个 PR 能不能合?」「CI 为什么挂?」「Issue 该分给谁?」)。系统要能:

1. **自己取证** —— 调工具去查 Issue、PR、CI 日志、当前代码、项目文档,而不是让模型凭空猜。
2. **自己判断** —— ChatAgent 用原生 Tool Calling 决定查什么,拿结果后继续判断下一步。
3. **按需协作** —— 需要综合判断时,拆成多 Agent 工作流(Planner → 专用 Agent → Observer → Synthesis),任务并行、依赖串行、失败跳过、冲突上报。
4. **如实交付** —— 回答带引用与证据,写操作只出草稿等人工确认,全程留运行轨迹。

**验收标准(必须逐条可复现):**

1. `docker compose up -d` 一条命令拉起 PostgreSQL + Milvus + FastAPI(:8000) + Next.js(:3000),`docker compose ps` 全部 healthy。
2. 前端工作台三个栏位结构与原文产品截图(img_01)一致:左侧项目/会话树、中间总览统计 + 对话流、右侧 Workspace 五个标签页;总览的六个统计数字来自 PostgreSQL 真实查询。
3. 提问「检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布」,SSE 逐事件可见 `plan → task_started → tool_call → tool_result → observation → done`,不是一次性整段返回。
4. 提问「分析 Issue #3 的优先级和复杂度」,返回 IssueAgent 的结构化结果(分类/优先级/复杂度/推荐负责人/行动项)。
5. 提问「PR #12 能不能合?」,进入多 Agent 工作流:Planner 拆任务、多个专用 Agent 并行、Observer 报告证据缺口与结论冲突、Synthesis 给出「建议合入/暂缓」结论。
6. 提问「CI #512 为什么失败」,CIDebugAgent 给出根因、关键错误块与修复步骤。
7. 提问「给 Issue #3 写一条查询评论草稿」,系统**不直接执行**,而是产出 ActionDraft;前端确认后才调用写接口,`audit_logs` 落一条记录。
8. RAG 问答带引用(文件名 + 标题路径);召回测试接口能分别展示切分、召回、RRF 融合、重排四个阶段的中间结果。
9. 跨会话记忆:会话 A 沉淀的经验进入候选池 → 人工批准 → 会话 B 能被召回。
10. `POST /api/eval/run` 跑固定评测集,输出硬规则通过率并落库;改动 Prompt/检索配置后可复跑对比。
11. `pytest` 全绿:**不打真实模型、不打网络**(全部走 Mock),单测覆盖核心逻辑。
12. 把 `.env` 从 `LLM_MODE=mock` 切到 `LLM_MODE=openai`(DeepSeek OpenAI 兼容端点)后,同样 12 条验收走通。

## 技术栈(定死,不可自行更换)

- **后端**:Python 3.12(容器内) + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic + SSE
- **Agent 编排**:LangChain + LangGraph + 原生 Tool Calling;通过 OpenAI 兼容接口接入模型
- **知识与证据**:PostgreSQL(事实与状态) + Milvus(向量) + Embedding + 混合检索 + RRF + Rerank;GitHub REST API;Workspace 工具读当前代码
- **能力扩展**:MCP(最小客户端 + 一个示例外部工具)、Skill Runtime(最小实现:YAML 声明流程 + 入参校验)
- **前端**:Next.js(App Router) + React + TypeScript + Tailwind CSS + React Query
- **质量与部署**:Ragas、pytest、pytest-asyncio、Docker Compose
- **依赖管理**:后端 `uv`,前端 `npm`

### 双模式开关(本项目最重要的工程约束)

Demo 必须**离线可跑、可单测**,同时又**能接真实上游**。所以两处都做双实现,由 `.env` 切换:

| 开关 | `mock`(默认) | 真实模式 |
|---|---|---|
| `LLM_MODE` | `DeterministicChatModel`:按 Agent 角色与输入信号确定性地产出 tool_calls 与结构化结果,**真实驱动** Agent 循环与 LangGraph 工作流 | `ChatOpenAI` → DeepSeek `https://api.deepseek.com/v1` |
| `EMBED_MODE` | 确定性 hash 向量(固定维度、可复现) | OpenAI 兼容 Embedding 端点 |
| `DATA_SOURCE` | `snapshot`:读 `backend/data/snapshot/*.json`,全离线、可复现 | `github`:GitHub REST 适配器(用户自填 token) |

三条约束:

- **Mock 不是假接口**。`DeterministicChatModel` 必须实现 `BaseChatModel`,返回真实的 `AIMessage.tool_calls`,让 ChatAgent 的循环、步数上限、重复调用拦截、错误处理全部被真实执行到 —— 否则单测等于没测。
- **模型名与地址只在 `.env`**。换上游改两行,不动代码。
- **单测永不联网**。真实模型/真实 GitHub 只用于手动验收,不进入 `pytest`。

## 架构:五层 + 单机 Compose

对齐原文架构图(img_09)的五个层次:

```
① 用户层        Next.js 工作台:Workspace / RAG 召回测试 / Evals
                        ↓ SSE ↑
② 应用服务层    FastAPI:Pydantic 校验 / SSE 事件流 / 会话与仓库范围
                        ↓
③ 智能协作层    ChatAgent(工具循环) ──需要综合判断──▶ 多 Agent 工作流
                     Planner → 专用 Agent(Issue/PR/CI/RAG/Safety) → Observer → Synthesis
                        ↓
④ 知识与工具层  RAG / Memory / GitHub / Workspace / MCP / Skill
                        ↓
⑤ 数据基础层    PostgreSQL(事实·状态·运行记录) / Milvus(向量) / 本地代码工作区
```

原文的链路口诀:**先定位 → 再取证 → 做判断 → 留痕迹**。本项目每个环节都有对应代码与验收项:

| 口诀 | 落在哪 | 验收 |
|---|---|---|
| 先定位 | ContextAssembler 组装仓库/会话/记忆/证据范围 | 验收 3 的 `context` 事件 |
| 再取证 | 工具层 8 个工具 + RAG 混合检索 | 验收 4/6/8 |
| 做判断 | ChatAgent 循环 + 多 Agent 工作流 | 验收 3/5 |
| 留痕迹 | AgentRun / WorkflowRun / TaskRun / AuditLog + SSE | 验收 7/10 |

**部署形态**:单机 Docker Compose,一个 `backend` 容器、一个 `frontend` 容器,加 `postgres`、`milvus`(standalone,含 etcd + minio)。`backend` 只暴露 `:8000`,`frontend` 只暴露 `:3000`,两者通过服务名互联。
## 目录结构

```
backend/
  app/
    main.py                     # FastAPI 入口,lifespan 内建表/装载快照/建 Milvus collection
    config.py                   # pydantic-settings 读 .env(含三个双模式开关)
    db/
      session.py                # SQLAlchemy engine / SessionLocal
      models.py                 # 全部 ORM 模型
      seed.py                   # 从 data/snapshot 装载 Issue/PR/CI/文档
    schemas/                    # Pydantic:请求/响应/各 Agent 结构化输出
      chat.py  issue.py  pr.py  ci.py  draft.py  memory.py  eval.py  run.py
    api/
      chat.py                   # POST /api/chat/stream  (SSE)
      repos.py                  # GET  /api/repos  /api/repos/{id}/health
      issues.py  prs.py  ci.py  # Workspace 右栏数据源
      drafts.py                 # GET/POST /api/drafts  {id}/confirm  {id}/reject
      memory.py                 # GET/POST /api/memory/candidates  {id}/approve
      rag.py                    # POST /api/rag/query  /api/rag/recall-test
      runs.py                   # GET  /api/runs/{run_id}  完整运行轨迹
      eval.py                   # POST /api/eval/run  GET /api/eval/runs
      mcp.py                    # GET  /api/mcp/tools     列出已接入的外部工具
    core/
      llm.py                    # 双模式模型工厂:get_chat_model / get_structured_model
      embeddings.py             # 双模式 Embedding:mock 确定性 / OpenAI 兼容
      prompts/                  # 每个 Agent 的 prompt 单独成文件,集中管理
      context.py                # ContextAssembler:组装仓库/会话/记忆/证据
      budget.py                 # 上下文预算分配与逐级压缩
      memory.py                 # 会话摘要 + MemoHub(候选池/批准/召回)
      errors.py                 # 工具错误归类与上报
    agents/
      base.py                   # Agent 基类:输入证据 + prompt + Pydantic 输出
      chat_agent.py             # 原生 Tool Calling 循环 + 执行约束
      issue_agent.py            # 分类/优先级/复杂度/负责人/行动项
      pr_review_agent.py        # 结合改动与证据评估风险
      ci_debug_agent.py         # 失败日志根因与修复步骤
      planner.py  observer.py  synthesis.py
      orchestrator.py           # LangGraph 工作流:依赖调度/并行/失败跳过/有限重规划
    tools/
      registry.py               # 工具注册表(名称/schema/实现/是否写操作)
      repo_health.py            # 仓库健康全景
      search_docs.py            # 研发资料检索(RAG)
      search_code.py            # Workspace:当前代码搜索
      analyze_issue.py          # 触发 IssueAgent
      review_pr.py              # 触发 PRReviewAgent
      debug_ci.py               # 触发 CIDebugAgent
      safety_check.py           # 安全风险评估
      draft_action.py           # 生成写操作草稿
      weekly_report.py          # 周报生成与回写
    rag/
      splitter.py               # 结构感知切分(标题层级 + 代码边界)
      indexer.py                # 切分→Embedding→Milvus 入库(按 repo 隔离)
      retriever.py              # 向量召回 + 关键词召回 + RRF 融合
      rerank.py                 # 重排
      pipeline.py               # 对外统一检索入口,返回带引用的证据
    github/
      client.py                 # GitHub REST(httpx):分页/退避/ETag/错误映射
      provider.py               # snapshot | github 双实现,同一接口
    mcp/
      client.py                 # 最小 MCP 客户端(stdio/HTTP 二选一)
      servers/local_tools.py    # 一个示例外部工具,证明扩展通道可用
    skills/
      runtime.py                # 最小 Skill Runtime:加载/校验/执行
      skills/*.yaml             # 可复用流程声明
    safety/
      policy.py                 # 角色与写操作白名单校验
      drafts.py                 # ActionDraft 生命周期
      audit.py                  # AuditLog 写入
    observability/
      events.py                 # SSE 事件模型与序列化
      tracing.py                # AgentRun/WorkflowRun/TaskRun/ToolCall 落库
    eval/
      harness.py                # 评测执行器
      rules.py                  # 硬规则检查
      ragas_runner.py           # Ragas 指标(真实模型模式)
  data/snapshot/                # 内置研发数据快照(离线可复现)
    repos.json  issues.json  pull_requests.json  ci_runs.json
    ci_logs/*.log  code/  docs/
  alembic/                      # 迁移
  tests/                        # pytest,全 Mock
  pyproject.toml  Dockerfile

frontend/
  app/
    layout.tsx  page.tsx        # 工作台主页面
    rag/page.tsx                # RAG 召回测试页
    evals/page.tsx              # Evals 页
  components/
    ProjectSidebar.tsx          # 左栏:项目/会话树 + 添加项目 + 刷新
    OverviewBar.tsx             # 顶部:仓库/会话/环境 + 六个统计卡片
    ChatPanel.tsx               # 中栏:消息流 + SSE 实时进度 + 快捷指令 + 输入框
    WorkspacePanel.tsx          # 右栏:Issue/PR/CI/团队/记忆&知识库 标签页
    IssueList.tsx  PrList.tsx  CiList.tsx
    RunTrace.tsx                # 执行轨迹:规划/工具调用/任务状态
    DraftCard.tsx               # 草稿确认卡片
    EvidenceList.tsx            # 引用与证据
  lib/
    api.ts                      # 运行时配置与 REST 封装
    sse.ts                      # SSE 客户端(EventSource/fetch-stream)
    types.ts                    # 与后端对齐的类型
  Dockerfile  tailwind.config.ts  package.json

docker-compose.yml              # postgres + etcd + minio + milvus + backend + frontend
.env.example  Makefile  README.md
```

## 数据模型(PostgreSQL)

事实与状态存关系库;向量只进 Milvus,PostgreSQL 只留切分元数据(便于关键词召回与引用回链)。

```
repos            id, owner, name, default_branch, workspace_path, created_at
sessions         id, repo_id, title, created_at
messages         id, session_id, role, content, run_id, created_at
issues           id, repo_id, number, title, body, state, labels, author, assignee, created_at
pull_requests    id, repo_id, number, title, body, state, head_ref, base_ref, additions, deletions,
                 changed_files, merged, author, created_at
pr_files         id, pr_id, path, additions, deletions, patch_summary, is_high_risk
ci_runs          id, repo_id, number, workflow, branch, status, conclusion, commit_sha, log_path, created_at
documents        id, repo_id, path, title, doc_type, version, updated_at
chunks           id, document_id, repo_id, chunk_index, heading_path, content, token_count, milvus_id
memory_candidates id, repo_id, session_id, run_id, content, confidence, status, created_at
memory_entries   id, repo_id, content, source_candidate_id, approved_by, embedding_id, created_at
action_drafts    id, repo_id, run_id, action, target, payload, preview, risk_level,
                 status, requested_by_role, decided_by_role, created_at, decided_at
audit_logs       id, draft_id, action, target, result, detail, created_at
agent_runs       id, session_id, repo_id, question, status, mode, started_at, finished_at,
                 total_tokens, stop_reason
workflow_runs    id, agent_run_id, question, status, replan_count, started_at, finished_at
task_runs        id, workflow_run_id, task_key, agent, title, depends_on, status, output, started_at, finished_at
tool_calls       id, agent_run_id, task_run_id, tool, args, result_summary, error, latency_ms, created_at
eval_runs        id, dataset, mode, total, passed, failed, metrics, started_at, finished_at
eval_cases       id, eval_run_id, case_key, question, expected, actual, rule_results, passed
```

关键约束:

- `pr_files.is_high_risk` 在入库时判定,高风险路径集合放在 `app/safety/policy.py`,不要散落在 Prompt 里。
- `chunks.milvus_id` 与 Milvus 主键一一对应;删除文档要同时清两处。
- `action_drafts.status` 状态机:`pending → confirmed → executed`,或 `pending → rejected`,或 `pending → expired`;`executed/rejected` 时必须写 `audit_logs`。
- 所有 `*_runs` 表都要能按 `agent_run_id` 串起来,这是「留痕迹」和验收 10 的基础。
## 接口契约

### POST /api/chat/stream —— SSE 流式对话(核心接口)

请求:

```json
{
  "session_id": "sess-1",
  "repo_id": 1,
  "message": "PR #12 能不能合?",
  "role": "member"
}
```

响应 `text/event-stream`。**事件是这条链路的可观测性载体**,前端右栏的执行轨迹直接由它渲染:

```
event: run_started
data: {"run_id": 12, "session_id": "sess-1", "repo_id": 1, "mode": "mock"}

event: context
data: {"repo": "clowder-ai", "history_turns": 4, "memory_hits": 2, "budget": {"total": 8000, "used": 3120}}

event: plan
data: {"workflow_run_id": 5, "tasks": [
        {"task_key": "t1", "agent": "issue_agent", "title": "梳理关联 Issue", "depends_on": []},
        {"task_key": "t2", "agent": "pr_review_agent", "title": "评估 PR 改动风险", "depends_on": []},
        {"task_key": "t3", "agent": "ci_debug_agent", "title": "检查失败 CI", "depends_on": []},
        {"task_key": "t4", "agent": "synthesis", "title": "汇总工程结论", "depends_on": ["t1","t2","t3"]}]}

event: task_started   data: {"task_key": "t1", "agent": "issue_agent", "title": "梳理关联 Issue"}
event: tool_call      data: {"task_key": "t1", "tool": "analyze_issue", "args": {"number": 24}}
event: tool_result    data: {"task_key": "t1", "tool": "analyze_issue", "summary": "分类=Bug 优先级=P0", "evidence_refs": ["issue#24"]}
event: task_finished  data: {"task_key": "t1", "status": "succeeded", "output": {"priority": "P0"}}

event: observation    data: {"gaps": ["缺少 CI #512 的完整日志"], "conflicts": ["PR 结论为可合,但 CI 结论为阻塞"], "safety": {"level": "low"}}

event: token          data: {"delta": "结论:"}
event: citation       data: {"path": "docs/api.md", "heading_path": "登录接口 > v1.2 变更", "score": 0.83}

event: draft          data: {"draft_id": 7, "action": "comment_on_issue", "target": "issue#3", "preview": "..."}

event: done
data: {"run_id": 12, "answer": "...", "citations": [...], "next_steps": [...], "stop_reason": "completed"}

event: error          data: {"message": "上游模型暂时不可用,请稍后重试"}
```

契约要点:

- 每个事件都是**一条独立可解析的 SSE 帧**,前端能在事件到达时就渲染进度,不必等 `done`。
- `stop_reason` 枚举:`completed` / `max_steps` / `repeated_tool_call` / `tool_error_limit` / `upstream_error` / `cancelled`。**任何非 `completed` 都必须能在轨迹里查到原因**(对应文章亮点 9)。
- 上游出错:推 `event: error` 后关流,已完成部分的 `tool_calls` 仍要落库。
- SSE 心跳:每 15s 无事件时推 `: ping` 注释行,避免反向代理断连。

**这三条契约的实现说明(2026-10-06 补)**:

- `token` 是**真实的模型增量**:走 `BaseChatModel.astream`,token 到达即推送。
  实测真实模型一次回答产生 512 个增量帧、分散在约 6 秒内。
  前端用增量做流式渲染,**`done.answer` 到达时覆盖增量缓冲** —— 真实模型在工具调用轮
  也会吐正文(实测第一句是「I'll analyze the failed CI run #512.」),所以必须有
  一个明确的权威来源,否则用户会看到正文和答案粘在一起。
- 多 Agent 工作流的最终结论来自**结构化输出**(`Synthesis`),JSON 不适合逐字渲染,
  因此工作流路径只在结束时刻推送一次完整结论。这是**已知差异**,不是漏做。
- `cancelled`:**已实现**。客户端断开时 SSE 生成器置位取消事件,Agent 在
  **每个步骤边界和每个 token 之间**检查;工作流在每个任务发起前检查。
  断开后给 5 秒协作式收尾窗口(让部分结果与轨迹能落库),超时由定时器硬取消。
  轨迹记为 `status=cancelled` / `stop_reason=cancelled`,且**被中断的运行不沉淀记忆**。
- `total_tokens`:**已实现**,取自模型上报的 `usage_metadata`(流式路径需
  `stream_usage=True`)。模型不上报时记 0 —— 不用字数估算冒充真实用量。

### 其余 REST 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/repos` | 仓库列表(左栏) |
| GET | `/api/repos/{id}/health` | 总览六项统计:待处理 Issue / 待 Review PR / 已处理 Issue / 已拒绝 Issue / 失败 CI / 已合并 PR |
| GET | `/api/repos/{id}/issues?state=&assignee=&q=` | 右栏 Issue 标签页(含分组计数:未归档/讨论中/待决策/已处理/已拒绝/已关闭) |
| GET | `/api/repos/{id}/prs` · `/ci` | 右栏 PR / CI 标签页 |
| GET | `/api/runs/{run_id}` | 完整轨迹:agent_run + workflow_runs + task_runs + tool_calls |
| POST | `/api/rag/query` | 直接检索,返回带引用的证据 |
| POST | `/api/rag/recall-test` | 四阶段中间结果:切分 / 向量召回 / 关键词召回 / RRF+重排 |
| GET | `/api/drafts?status=pending` | 草稿列表 |
| POST | `/api/drafts/{id}/confirm` · `/reject` | 人工决策;**confirm 才真正执行写操作** |
| GET | `/api/memory/candidates` · POST `/{id}/approve` | 记忆候选池与批准 |
| POST | `/api/eval/run` · GET `/api/eval/runs` | 评测执行与历史 |
| GET | `/api/mcp/tools` | 已接入的外部工具清单 |

错误约定:参数校验 422(Pydantic);找不到资源 404;上游(模型/GitHub)失败 502,`detail` 用人话说明;写操作越权 403,并记 `audit_logs`。

## Agent 设计

### ChatAgent —— 工具循环与执行约束

对应文章亮点 3。用原生 Tool Calling,不用手写正则解析:

```
messages = [system(角色+可用工具+约束)] + assembled_context
loop:
    resp = model.invoke(messages)
    if not resp.tool_calls: break            # 模型认为信息够了
    for call in resp.tool_calls:
        guard(call)                          # ← 执行约束在这里
        result = registry.execute(call)
        messages.append(ToolMessage(result))
```

执行约束(每一条都要有测试):

- `max_steps = 8`:超限停止,`stop_reason = "max_steps"`,把已有结论交付,不静默失败。
- **重复调用拦截**:同一 `(tool, 规范化参数)` 出现第 2 次即停止,`stop_reason = "repeated_tool_call"`。这是原文明确要求的「限制重复调用」,不是可选优化。
- **工具错误处理**:工具异常转成带 `error` 的 `ToolMessage` 回灌,让模型有机会换路子;连续 3 次错误即停止(`tool_error_limit`)。
- **路由到多 Agent**:ChatAgent 只负责「需不需要综合判断」。需要时调用 `workflow` 工具进入 LangGraph 工作流,简单查询自己调工具收尾。

### 专用 Agent(各自独立,不做万能 Prompt)

对应文章亮点 4。三者共享基类,但 Prompt、输入证据、Pydantic 输出结构**完全分开**,可以单独测、单独调:

| Agent | 输入证据 | 输出(Pydantic) |
|---|---|---|
| `IssueAgent` | Issue 正文与评论、标签、历史相似 Issue | `category`(Bug/Feature/Question/Docs/Chore)、`priority`(P0-P3)、`complexity`(S/M/L)、`recommended_assignee`、`action_items[]`、`rationale` |
| `PRReviewAgent` | PR diff 摘要、改动文件、高风险标记、关联 Issue、Review 评论 | `decision`(merge/hold)、`risk_level`(low/medium/high)、`high_risk_paths[]`、`findings[]`、`missing_checks[]` |
| `CIDebugAgent` | 失败 CI 日志、提交信息、相关文件 | `root_cause`、`error_blocks[]`(原文片段)、`fix_steps[]`、`related_files[]`、`confidence` |

### 多 Agent 工作流(LangGraph)

对应文章亮点 5、原文全局链路图第 ④ 段。

```
        ┌──────────┐
        │ Planner  │  拆任务:产出 tasks[] + depends_on
        └────┬─────┘
             │  (按依赖扇出,无依赖的并行)
   ┌─────────┼─────────┬──────────┐
   ▼         ▼         ▼          ▼
IssueAgent PRReview  CIDebug   SafetyAgent
   └─────────┴─────────┴──────────┘
             ▼
        ┌──────────┐
        │ Observer │  证据缺口 / 结论冲突 / 安全条件
        └────┬─────┘
             │ 缺口存在 且 replan_count < 2
             ├──────────▶ 回到 Planner(有限重规划)
             ▼
        ┌───────────┐
        │ Synthesis │  汇总工程结论:结论 + 依据 + 下一步
        └───────────┘
```

硬性规则:

- **任务依赖**:`depends_on` 未完成不得启动。
- **失败跳过**:依赖任务失败 → 下游任务标记 `skipped`,不静默当作成功。
- **有限重规划**:`replan_count` 上限 2,超限直接进 Synthesis 并在结论里说明「证据不足」,不允许无限空转。
- **并行**:无依赖任务真并行(`asyncio.gather`),并行度上限 4,避免打爆上游限流。
- **Observer 必须能报告冲突**:PR 结论「可合」而 CI 结论「阻塞」这类冲突要显式出现在 `observation` 事件与最终结论里,这是这个工作流存在的意义。
## RAG 设计

对应文章亮点 2、原文「RAG 工程化检索」。**RAG 只是证据来源之一**,不是这个项目的全部 —— 这条边界要在代码里体现出来。

### 数据分流(先分流,再检索)

对应文章亮点 1。原文把这件事说得最清楚:*减少拿过期文档解释当前代码、用历史讨论判断最新状态的问题*。

| 问题类型 | 取证通道 | 工具 |
|---|---|---|
| 当前代码长什么样 | 本地 Workspace(代码索引/grep) | `search_code` |
| Issue/PR/CI 的**实时状态** | PostgreSQL / GitHub REST | `repo_health`、`analyze_issue`、`review_pr`、`debug_ci` |
| 历史文档、设计说明、讨论 | RAG(Milvus + 关键词) | `search_docs` |

**代码永不进 RAG 向量库**。代码会天天变,向量库里的代码副本必然过期;这条规则由 `search_code` 只能读工作区、`search_docs` 只能读 `documents` 表来保证。

### 切分(结构感知,不按字数硬切)

- Markdown:按 `#/##/###` 标题层级切,chunk 携带 `heading_path`(如「登录接口 > v1.2 变更」),超长小节再按段落二次切分,并保留 1 段重叠。
- 代码/配置:按 `def/class/` 函数边界切(简化规则),chunk 携带符号名。
- 每个 chunk 记录 `document_id / heading_path / chunk_index / token_count`,供引用回链。

### 混合检索 + RRF + 重排

```
query ─┬─▶ Milvus 向量召回 top-20 ─┐
       └─▶ PostgreSQL 关键词召回 top-20 ─┴─▶ RRF(k=60) 融合 top-10 ─▶ Rerank ─▶ top-6 证据
```

- **仓库隔离**:所有检索强制带 `repo_id` 过滤,跨仓库内容不得进入证据集。这是隔离性要求,要有测试。
- **引用**:最终回答里每条结论都要能对应到 `chunk`(文件名 + heading_path),前端 `EvidenceList` 渲染。
- **检索不到就明说**:证据为空时返回「知识库中未找到相关内容」,**不允许模型自由发挥**。
- **召回测试**(`POST /api/rag/recall-test`):一次返回切分/向量召回/关键词召回/RRF+重排四阶段结果,用于诊断「是切分坏了、排序坏了,还是过滤把正确结果滤掉了」。

### 评测

`docs/` 下固定一批问答对(问题 → 期望证据 chunk)。改动切分/召回/重排后可复跑,比较命中率变化。

## 上下文预算与长期记忆

对应文章亮点 6、原文「上下文预算和长期记忆」。

### 上下文组成与预算分配

`ContextAssembler` 按固定优先级组装,总预算默认 8000 token(`CONTEXT_BUDGET`,可配):

| 段 | 预算占比 | 超压时的处理顺序 |
|---|---|---|
| system(角色+工具+约束) | 固定,不裁剪 | 永不裁剪 |
| 历史摘要 | 10% | 二次摘要 |
| 最近对话原文 | 30% | 从最旧一轮开始丢弃 |
| 工具结果 | 30% | 先转成一句摘要,再丢弃 |
| 检索证据 | 剩余 | 按 rerank 分数从低到高截断 |

**压缩顺序是设计的一部分,不是实现细节**:先压工具结果(信息密度最低、可重取),再截证据(可按分数重取),最后才动对话历史。

### 跨会话记忆(候选 → 批准 → 召回)

MemHub 三段式:

1. **沉淀**:一次运行结束后,把「值得跨会话复用」的结论写入 `memory_candidates`,附 `run_id` 与置信度。**不直接生效**。
2. **批准**:人工在右栏「记忆&知识库」标签页批准(`POST /api/memory/candidates/{id}/approve`),才写入 `memory_entries` 并进向量库。
3. **召回**:后续会话检索时,`memory_entries` 与文档证据一起参与召回,但**标记来源为「已确认记忆」**,与文档证据在 UI 上区分。

未批准的候选**绝不参与召回** —— 这是防止错误结论被长期沿用的闸门(原文明确要求「经过人工批准后再参与召回」)。

## 安全:草稿 + 人工确认 + 审计

对应文章亮点 8、原文「模型提出操作,系统负责检查执行条件」。

**写操作白名单**:`comment_on_issue` / `add_labels` / `close_issue` / `reopen_issue`。白名单之外一律拒绝。

流程(四道闸):

```
模型提出写操作
  ① safety_check:判断动作是否在白名单、目标是否属于当前仓库、payload 是否合法
  ② 生成 ActionDraft(status=pending),返回前端展示 preview  ← 到这里为止都没有副作用
  ③ 人工在前端点「确认」→ policy 校验角色权限(viewer 无写权限 → 403 并记审计)
  ④ 通过才调用写接口(snapshot 模式写本地快照副本;github 模式调真实 API)
  ⑤ 无论成功失败,audit_logs 落一条
```

硬性规则:

- **模型永远拿不到直接执行写操作的通道**。工具层只有 `draft_action`,没有 `execute_action`。
- 高风险动作(如 `close_issue`)在 draft 上标 `risk_level=high`,前端二次确认。
- 审计记录必须包含:谁、什么角色、什么时候、对哪个目标、执行结果。
- 越权尝试也要记审计(403 也要留痕)。

## 可观测:流式进度与运行轨迹

对应文章亮点 9、原文「回答出错时,可以沿着记录检查是工具参数有误、检索证据不足,还是多个任务的结论出现了冲突」。

- **SSE 事件流**:见上文接口契约,前端 `RunTrace` 组件实时渲染规划、工具调用、任务状态。
- **落库轨迹**:`agent_runs` → `workflow_runs` → `task_runs` → `tool_calls` 四级关联,`GET /api/runs/{run_id}` 一次取全。
- **停止原因必须留痕**:`stop_reason` 与触发它的那一步(第几次调用、哪个工具、什么参数)一起入库。
- 前端「Evals」页与「运行轨迹」抽屉共用这套数据,不做第二份实现。

## Agent Eval 与回归验证

对应文章亮点 10、原文「用固定评测集、RAGAS、逐题证据和硬规则检查回答与执行过程」。

- **固定评测集**:`tests/data/eval_cases.json`,覆盖 Issue 分诊 / PR 审查 / CI 排障 / 知识问答 / 安全越权五类,约 10 题。
- **硬规则检查**(不依赖模型判分,`mock` 模式也能跑):
  - 期望工具轨迹:本题必须调用过某个工具;不应调用的工具不得出现。
  - 期望结构化字段:如 Issue #24 的 `priority` 必须为 `P0`。
  - 必须带引用:知识问答类题目 `citations` 不得为空。
  - 安全红线:任何评测题的运行轨迹里都**不得出现已执行的写操作**(只能有 draft)。
  - 停止原因:正常题目必须 `completed`。
- **RAGAS**:`faithfulness` / `answer_relevancy` / `context_precision` 三项,仅在真实模型模式启用(需模型判分);`mock` 模式跳过并在结果里显式标注 `ragas: skipped (mock mode)`,不得用假数字充数。
- **可回归**:`POST /api/eval/run` 记录一次 `eval_runs`;改 Prompt / 检索配置 / 工具逻辑后复跑同组题,对比通过列表的增删,把「改善、退步、失败原因」都留下来。
## 前端 UI 规格(复刻 img_01 工作台)

严格照原文流出的产品截图(img_01)还原三栏结构。视觉上可以现代化,但**信息架构不得改动**。

### 左栏 · 项目与会话

- 顶部品牌块:`DevFlow AI`,副标题「研发团队 PR / Issue 智能协作」。
- `PROJECTS / 项目` 分组:仓库节点(如 `clowder-ai`)下挂会话(「默认会话 5天」「第二个会话测试 5天」),显示相对时间。
- 底部:`+ 添加项目`、`刷新当前项目`。

### 中栏 · 总览 + 对话

- 顶栏:`总览`、当前代码仓 `owner/repo`、`会话:xxx`、环境标记 `Production Workspace`、`管理项目`、`刷新`。
- **六个统计卡片**(数据必须来自 `GET /api/repos/{id}/health`,不得前端写死):
  `待处理 Issue` / `待 Review PR` / `已处理 Issue` / `已拒绝 Issue` / `失败 CI` / `已合并 PR`。
- 对话流:系统提示(「已切换到仓库 xxx / 会话 xxx。你可以直接问我 Issue、PR、CI 或周报相关问题。」),然后是消息列表。
- **每条助手消息内嵌执行轨迹**:可折叠的规划 → 工具调用 → 任务状态时间线,数据来自 SSE 事件。
- 结论区:结论 + 引用列表(`EvidenceList`)+ 下一步建议。
- **草稿卡片**:`ActionDraft` 以卡片呈现 preview,带「确认执行 / 拒绝」按钮,确认后卡片状态变更。
- 快捷指令 chips(照截图,至少三条):`Issue #3: Feature: 增加桌面化能力 应该分给谁?`、`分析 Issue #3 的优先级和复杂度`、`给 Issue #3 写一条查询评论草稿`。
- 输入框占位符「输入消息,问问当前代码仓…」,回车发送,流式期间禁用并显示停止按钮。

### 右栏 · Workspace

五个标签页:`Issue` / `PR` / `CI` / `团队` / `记忆&知识库`。

- **Issue 标签页**(照截图):搜索框(「关键词搜索标题、正文、标签」)、三个筛选下拉(全部状态 / 全部负责人 / 全部时间)、分组计数(`未归档 2`、`讨论中 0`、`待决策 0`、`已处理 0`、`已拒绝 0`、`已关闭 0`)、Issue 卡片列表(编号 + 标题 + 状态 + 正文摘要)。
- **PR / CI 标签页**:同构列表,PR 显示「建议合入/暂缓」与高风险标记,CI 显示失败结论与耗时。
- **记忆&知识库**:两个区 —— 待批准候选(带批准/忽略)与已生效记忆(带来源运行)。
- 每个列表项可「引用到对话」,把编号塞进输入框。

### 两个附加页

- `/rag`:`RAG 召回测试`,输入 query 后并列展示切分 / 向量召回 / 关键词召回 / 融合重排四个阶段。
- `/evals`:`Evals`,触发评测、展示通过率与逐题规则明细、历史运行对比。

## 数据接入:GitHub 适配器与快照

对应文章亮点 1 的「实时状态走数据库或 GitHub API」。同一接口两套实现(`github/provider.py`):

- `DATA_SOURCE=snapshot`(默认):读 `backend/data/snapshot/*.json` + `ci_logs/*.log`。**离线、确定、可复现**,是开发与单测的唯一数据源。
- `DATA_SOURCE=github`:`GitHubClient`(httpx)调真实 REST —— 分页(Link header)、速率限制退避(403/429 读 `X-RateLimit-Reset`)、ETag 缓存、错误映射(404/401/403 → 领域异常)。CI 日志走 Actions API。

约束:

- token 只放 `.env` 的 `GITHUB_TOKEN`,**不落库、不进日志、不进 Prompt**。
- `github` 模式下若未配置 token,启动**不报错**,但相关工具返回明确的「未配置 token」错误,前端可见 —— 而不是静默回退到快照(静默回退会让人把假数据当真实结论)。
- 快照数据要**自洽**:Issue #24 的标题、PR #12 的关联 Issue、CI #512 的失败日志必须能互相印证,否则多 Agent 的冲突检测没有意义。

## 测试与验证

按「可单测的走 TDD、纯 Prompt 产出走标注样例验证」拆两类。

### TDD(pytest,先红后绿,全程 Mock,不联网)

| 模块 | 必须覆盖的行为 |
|---|---|
| `core/budget.py` | 预算分配；超压时**按设计顺序**压缩(工具结果→证据→历史);system 段永不被裁 |
| `agents/chat_agent.py` | 工具循环；`max_steps` 停止；同参数重复调用第 2 次即停；工具异常回灌；连续错误上限 |
| `agents/orchestrator.py` | 依赖未满足不启动；无依赖并行；依赖失败下游 `skipped`；重规划上限 2;Observer 冲突被传递 |
| `rag/retriever.py` | RRF 融合排序；`repo_id` 隔离(跨仓库证据必须被滤掉)；空结果不臆造 |
| `rag/splitter.py` | 标题层级切分与 `heading_path` 正确；超长小节二次切分与重叠 |
| `safety/drafts.py` | 状态机 `pending→confirmed/rejected`；白名单外动作拒绝；越权 403 且记审计；模型无直接执行通道 |
| `memory.py` | 候选未批准不参与召回；批准后进召回并被标记来源 |
| `tools/registry.py` | 工具 schema 与实现一致；写类工具**只有** `draft_action` |
| `api/chat.py` | SSE 组帧(逐事件、可解析、`[DONE]` 语义)；上游异常推 `error` 帧且已完成的 `tool_calls` 已落库 |
| `github/client.py` | 分页拼装、429 退避、错误映射(用 respx/mock transport,不打网络) |

### 标注样例验证(真实模式)

- `tests/data/eval_cases.json` 十题跑 `POST /api/eval/run`,硬规则全过。
- 真实 DeepSeek 端点跑一遍验收 3/4/5/6,人工核对结论质量与引用是否成立。
- `DATA_SOURCE=github` 下用真实 token 跑一次 `repo_health` 与 `analyze_issue`,确认适配器可用。

### 端到端验收脚本

`scripts/verify.sh`:依赖 `docker compose ps` 全 healthy → 依次跑验收 1-12,输出 PASS/FAIL 汇总。这是最终交付的**唯一权威验收入口**,不允许只在聊天里口头确认。

## 本 Demo 不做

明确划界,避免范围失控:

- **不搬运课程内容**。不做 16 章、60+ 篇文档、25 万字;原文的课程目录(img_14)只作为功能范围的依据。
- **不替用户改代码、不自动合并 PR**。原文明确 DevFlow AI 是协作型而非代码执行型 Agent。
- **不做生产级鉴权**。角色由前端切换 / 请求头传入,只用于演示权限闸门;不做 SSO、多租户、限流。
- **不做完整 MCP 规范**。只做一个最小客户端 + 一个示例外部工具,证明扩展通道打通。
- **Skill Runtime 做最小版**:YAML 声明流程 + 入参校验 + 执行,不做 marketplace。
- **Ragas 只接三项核心指标**,且仅在真实模型模式启用。
- **前端只做工作台相关页面**,不做完整设计系统、不做移动端适配。
- **不做实时 WebSocket**。进度用 SSE,单向足够。

## 关键决策记录

| 决策 | 选择 | 备选与理由 |
|---|---|---|
| Demo 范围 | 端到端最小闭环(八大能力各留一条可验收的细路径) | 全量复刻 16 章不现实;只做单模块则体现不出「多 Agent 协作」这个项目真正的卖点 |
| LLM 接入 | 双模式,mock 为默认 | 只接真实模型 → 无 key 不能跑、单测不稳定;只做 mock → 看不到真实分析质量。双模式代价是一个 `BaseChatModel` 子类 |
| Mock 的形态 | 实现 `BaseChatModel`,真实产出 `tool_calls` | 用「预录回放」最省事,但那样 Agent 循环/步数上限/重复调用拦截全都没被真正执行,单测形同虚设 |
| 研发数据 | `snapshot` 默认可选 `github` | 用户要求真实 GitHub;但开发与单测必须可复现,故同一接口两套实现,由 `.env` 切换 |
| 数据库 | PostgreSQL + Milvus 真实容器 | 用户明确要求「严格按文章」,不用 SQLite/内存向量替代;代价是启动重、需要 Docker 常驻 |
| Python 版本 | 容器内 3.12;宿主 3.14 | 文章与参考文档均为 3.12,容器锁 3.12 保证生态一致;宿主 3.14 仅用于编辑与部分本地脚本 |
| 代码是否进向量库 | 不进 | 代码天天变,向量库副本必然过期;当前代码只走 Workspace 工具 |
| 向量库隔离 | `repo_id` 过滤 | 多租户场景 partition_key 更优,但过滤方案更易验证正确性,先做对再做快 |
| 记忆生效 | 候选 + 人工批准 | 自动生效会让一次错误结论污染后续所有会话 |
| 写操作 | 只有 `draft_action`,无执行工具 | 让模型「有能力但不越权」;执行权留在人工确认环节 |
| 角色来源 | 服务端从请求头解析,请求体/查询参数不参与授权 | 原先角色由客户端在请求体自称,任何人写 `role=maintainer` 就能写 —— 那样的「越权被拦下」是演示出来的,不是系统保证的 |
| 认证强度 | 可选共享令牌(`DEVFLOW_ROLE_TOKENS`);未配置时为演示模式并如实标注 | 没有用户体系就不假装有;`/api/auth/mode` 暴露 `enforced` 供界面提示 |
| 停止条件 | 显式 `stop_reason` 落库 | 只返回「没答出来」无法排查;原文要求能追溯是工具参数、证据还是结论冲突的问题 |
| 前端 | Next.js + React + TS + Tailwind | 照文章技术栈;用户明确选择 |