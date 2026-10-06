"""LLM 双模式工厂 + 确定性 Mock 模型。

为什么 Mock 必须是一个真正的 BaseChatModel,而不是「预录回放」:
ChatAgent 的工具循环、max_steps 上限、重复调用拦截、工具错误回灌 ——
这些执行约束只有在模型真的返回 tool_calls 时才会被跑到。
用预录回放的话,循环体一次都不会执行,单测等于没测。

所以这里的 Mock 会:
1. 按 Agent 角色(system prompt 里的 [[AGENT_ROLE:x]] 标记)选择行为
2. 依据问题里的信号,挑一个工具并给出参数,返回真实的 AIMessage.tool_calls
3. 拿到工具结果后,把结果编排成结论并停止
4. 结构化输出模式下,从证据 JSON 里确定性地推导出 schema 字段
"""

from __future__ import annotations

import contextvars
import json
import re
from contextlib import contextmanager
from typing import Any, Iterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.config import settings
from app.core.prompts.roles import AgentRole, parse_role

# 路由判据与工具选择统一在 app.core.workflow_rules:
# 两处各写一份必然漂移,而 Mock 与真实模型的行为差异会因此变得无法解释。
from app.core.workflow_rules import (  # noqa: E402
    first_number as _first_number,
    needs_workflow as _needs_workflow,
    pick_tool as _pick_tool,
    tool_args as _args_for,
)
from app.schemas.ci import CIDebug, Confidence
from app.schemas.issue import Complexity, IssueCategory, IssueTriage, Priority
from app.schemas.pr import PRDecision, PRReview, RiskLevel
from app.schemas.safety import SafetyAssessment, SafetyLevel
from app.schemas.workflow import Observation, Plan, Synthesis, TaskSpec, WorkflowAgent
from app.core.workflow_rules import collect_facts, detect_conflicts, detect_gaps

# --------------------------------------------------------------------------- 工具选择规则

# 顺序有讲究:先判断「是不是复杂问题」,再挑单个工具。
# 抽出来做常量是为了让「为什么选中这个工具」在代码里一眼可见,而不是藏在 if 里。
def _tool_results(messages: list[BaseMessage]) -> list[dict]:
    out = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                out.append(json.loads(msg.content))
            except (TypeError, ValueError):
                out.append({"summary": str(msg.content)})
    return out


def _compose_answer(role: str, messages: list[BaseMessage]) -> str:
    results = _tool_results(messages)
    if not results:
        return "我已经收集到必要信息,但没有可用的工具结果可引用。"

    # 工作流的结果自带结论,直接用它
    for item in results:
        if isinstance(item, dict) and item.get("conclusion"):
            return str(item["conclusion"])

    lines: list[str] = ["依据已收集的证据:"]
    empty = False
    for item in results:
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") or item.get("error")
        if not summary:
            # 工具可能返回 {"root_cause": ...} 这类结构化字段,没有统一 summary。
            # 回退到标量值拼接,否则答案会空掉 —— 而空答案比错答案更难排查。
            scalars = [
                str(v).strip()
                for v in item.values()
                if isinstance(v, (str, int, float)) and str(v).strip()
            ]
            summary = " / ".join(scalars[:3])
        if summary:
            lines.append(f"- {summary}")
        if item.get("empty"):
            empty = True
    if empty:
        lines.append("")
        lines.append("未找到与该问题相关的项目资料,无法据此作答。")
        return "\n".join(lines)

    lines.append("")
    lines.append("以上结论仅基于当前仓库的证据,如需进一步确认可以指定具体的 Issue / PR / CI 编号。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 结构化输出


def _extract_evidence(messages: list[BaseMessage]) -> dict:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, ValueError):
                return {"raw": content}
    return {}


_AREA_OWNERS = {"auth": "wangwu", "ui": "lisi", "api": "zhangsan", "infra": "lisi"}


def _issue_triage(ev: dict) -> IssueTriage:
    labels = [str(x).lower() for x in ev.get("labels", [])]
    title = str(ev.get("title", ""))
    body = str(ev.get("body", ""))
    text = f"{title} {body}"

    if any("bug" in x for x in labels) or re.search(r"报错|失败|异常|崩溃|401|500", text):
        category = IssueCategory.BUG
    elif any("feature" in x for x in labels) or "feature" in title.lower():
        category = IssueCategory.FEATURE
    elif any("docs" in x for x in labels):
        category = IssueCategory.DOCS
    else:
        category = IssueCategory.QUESTION

    priority = Priority.P2
    for label in labels:
        found = re.search(r"priority:(p[0-3])", label)
        if found:
            priority = Priority(found.group(1).upper())
            break

    complexity = Complexity.S
    if len(body) > 400:
        complexity = Complexity.L
    elif len(body) > 150:
        complexity = Complexity.M

    assignee = "未分配"
    for label in labels:
        found = re.search(r"area:(\w+)", label)
        if found and found.group(1) in _AREA_OWNERS:
            assignee = _AREA_OWNERS[found.group(1)]
            break

    if category is IssueCategory.BUG:
        actions = ["复现问题并补充回归测试", "定位根因并发布修复", "补充同类问题的监控告警"]
    elif category is IssueCategory.FEATURE:
        actions = ["拆解需求并评估工作量", "确认设计方案与影响面", "补充验收标准"]
    else:
        actions = ["补充上下文信息", "确认期望行为"]

    return IssueTriage(
        category=category,
        priority=priority,
        complexity=complexity,
        recommended_assignee=assignee,
        action_items=actions,
        rationale=f"依据标签 {labels or '无'} 与标题「{title}」判定为 {category.value},优先级 {priority.value}。",
    )


def _pr_review(ev: dict) -> PRReview:
    files = ev.get("files", []) or []
    # 刻意不看 CI 结论:PR Agent 只审「改动本身是否该合」,
    # CI 是否阻塞由 CI Agent 负责,两者的分歧正是 Observer 要抓的冲突。
    high_risk = [f.get("path", "") for f in files if f.get("is_high_risk")]
    blocking_reviews = [
        r for r in (ev.get("reviews") or [])
        if str(r.get("state", "")).upper() in ("CHANGES_REQUESTED", "REQUEST_CHANGES")
    ]

    risk = RiskLevel.LOW
    if high_risk:
        risk = RiskLevel.HIGH
    elif len(files) > 5:
        risk = RiskLevel.MEDIUM

    decision = PRDecision.HOLD if blocking_reviews else PRDecision.MERGE

    findings: list[str] = []
    if high_risk:
        findings.append("改动命中高风险路径:" + "、".join(high_risk) + ",需要额外 review")
    for review in ev.get("reviews") or []:
        findings.append(f"{review.get('author', '?')} 的意见:{review.get('body', '')}")
    if not findings:
        findings.append("未发现阻塞性问题")

    missing: list[str] = []
    if high_risk:
        missing.append("高风险路径的二次 review")
    if any("测试" in str(r.get("body", "")) for r in (ev.get("reviews") or [])):
        missing.append("评审提到的集成测试尚未补充")
    if not ev.get("related_issues"):
        missing.append("PR 未关联任何 Issue")

    return PRReview(
        decision=decision,
        risk_level=risk,
        high_risk_paths=high_risk,
        findings=findings,
        missing_checks=missing,
        rationale=(
            f"共 {len(files)} 个文件改动,其中 {len(high_risk)} 个命中高风险路径;"
            f"{'存在阻塞性评审意见' if blocking_reviews else '无阻塞性评审意见'}。"
        ),
    )


_ERROR_LINE_RE = re.compile(r"^(?:E\s+|.*(?:AssertionError|Error|FAILED|fatal|panic).*)$", re.MULTILINE)
_PATH_RE = re.compile(r"[\w./-]+\.(?:py|go|ts|tsx|js|yml|yaml|json|md):?\d*")


def _ci_debug(ev: dict) -> CIDebug:
    log = str(ev.get("log") or "")
    number = ev.get("number")

    if not log.strip():
        return CIDebug(
            root_cause=f"未找到 CI #{number} 的日志,无法定位根因。",
            error_blocks=[],
            fix_steps=["确认 CI 运行记录是否存在", "若构建产物已过期,重新触发一次同分支的 CI"],
            related_files=[],
            confidence=Confidence.LOW,
        )

    blocks: list[str] = []
    for line in log.splitlines():
        stripped = line.strip()
        if re.search(r"AssertionError|FAILED|\bE\s{2,}|fatal|panic|WARNING auth", stripped):
            cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", stripped)
            if cleaned not in blocks:
                blocks.append(cleaned)
        if len(blocks) >= 5:
            break

    root_cause = blocks[0] if blocks else "日志中没有出现明确的错误行,需要人工确认失败原因。"

    related = []
    for match in _PATH_RE.findall(log):
        path = match.split(":")[0]
        if path not in related:
            related.append(path)
    related = related[:5]

    steps = ["按日志中的关键错误块定位到对应代码分支", "补充覆盖该分支的集成测试", "修复后重跑同一分支的 CI 确认转绿"]

    return CIDebug(
        root_cause=root_cause,
        error_blocks=blocks,
        fix_steps=steps,
        related_files=related,
        confidence=Confidence.HIGH if blocks else Confidence.MEDIUM,
    )


def _safety_assessment(ev: dict) -> SafetyAssessment:
    action = str(ev.get("action") or "")
    reasons = []
    level = SafetyLevel.LOW
    if action in ("close_issue", "reopen_issue"):
        level = SafetyLevel.HIGH
        reasons.append(f"{action} 属于高风险写操作,会改变 Issue 状态")
    elif action:
        reasons.append(f"{action} 属于对外的写操作,必须留下可追溯记录")
    else:
        reasons.append("未指定具体动作,按只读场景处理")
    return SafetyAssessment(
        level=level,
        reasons=reasons,
        forbidden_actions=[] if action else ["任何未在白名单内的写操作"],
        draft_only=True,
    )


# --------------------------------------------------------------------------- 工作流三角色


_ISSUE_SIGNAL = re.compile(r"issue|问题", re.IGNORECASE)
_PR_SIGNAL = re.compile(r"\bprs?\b|pull request|合并|合入", re.IGNORECASE)
_CI_SIGNAL = re.compile(r"\bci\b|构建|流水线|失败", re.IGNORECASE)


def _plan(ev: dict) -> Plan:
    """拆任务。

    判据:问题提到哪类数据源,就派哪个专用 Agent。
    一类都没提到(比如「检查一下这个版本」),就三个都跑 —— 宁可多查不可漏查。
    """
    question = str(ev.get("question", ""))
    targets = ev.get("targets") or {}

    selected: list[tuple[str, str]] = []
    if _ISSUE_SIGNAL.search(question):
        selected.append((WorkflowAgent.ISSUE.value, "梳理关联 Issue 的分类与优先级"))
    if _PR_SIGNAL.search(question):
        selected.append((WorkflowAgent.PR_REVIEW.value, "评估 PR 改动风险"))
    if _CI_SIGNAL.search(question):
        selected.append((WorkflowAgent.CI_DEBUG.value, "检查失败 CI 的根因"))
    if not selected:
        selected = [
            (WorkflowAgent.ISSUE.value, "梳理关联 Issue 的分类与优先级"),
            (WorkflowAgent.PR_REVIEW.value, "评估 PR 改动风险"),
            (WorkflowAgent.CI_DEBUG.value, "检查失败 CI 的根因"),
        ]

    tasks: list[TaskSpec] = []
    keys: list[str] = []
    for index, (agent, title) in enumerate(selected, start=1):
        key = f"t{index}"
        keys.append(key)
        number = targets.get(agent)
        tasks.append(TaskSpec(task_key=key, agent=agent, title=title, depends_on=[], number=number))

    # 汇总任务依赖全部前置任务,保证它拿到的是完整证据
    tasks.append(
        TaskSpec(
            task_key="synthesis",
            agent=WorkflowAgent.SYNTHESIS,
            title="汇总工程结论",
            depends_on=list(keys),
            number=None,
        )
    )
    return Plan(tasks=tasks)


def _observation(ev: dict) -> Observation:
    facts = ev.get("facts") or collect_facts(ev.get("results") or [])
    return Observation(
        gaps=detect_gaps(facts, ev.get("tasks") or [], ev.get("degraded") or []),
        conflicts=detect_conflicts(facts),
        safety={"draft_only": True, "write_actions_require_confirmation": True},
    )


def _synthesis(ev: dict) -> Synthesis:
    facts = ev.get("facts") or collect_facts(ev.get("results") or [])
    conflicts = ev.get("conflicts") or detect_conflicts(facts)
    gaps = ev.get("gaps") or []
    question = str(ev.get("question", ""))

    evidence: list[str] = []
    for item in ev.get("results") or []:
        agent = item.get("agent")
        output = item.get("output") or {}
        if agent == WorkflowAgent.PR_REVIEW.value:
            evidence.append(
                f"PRReviewAgent:PR #{item.get('number')} 结论 {output.get('decision')},"
                f"风险 {output.get('risk_level')},高风险路径 {len(output.get('high_risk_paths') or [])} 处"
            )
        elif agent == WorkflowAgent.CI_DEBUG.value:
            evidence.append(
                f"CIDebugAgent:CI #{item.get('number')} 根因「{str(output.get('root_cause'))[:60]}」"
            )
        elif agent == WorkflowAgent.ISSUE.value:
            evidence.append(
                f"IssueAgent:Issue #{item.get('number')} 分类 {output.get('category')},"
                f"优先级 {output.get('priority')}"
            )

    if conflicts:
        conclusion = (
            f"结论:暂缓。针对「{question}」,各 Agent 的结论存在冲突,不能在当前证据下推进。"
            + conflicts[0]
        )
        confidence = "medium"
        next_steps = [
            "先解决 PR 审查意见与 CI 失败之间的不一致,再重新评估能否合入",
            "把失败 CI 的修复范围限定在登录链路,避免扩大改动面",
            "修复后重跑同一分支 CI,确认转绿再走合入流程",
        ]
    elif gaps:
        conclusion = f"结论:证据不足,暂不下最终判断。针对「{question}」仍缺少:" + gaps[0]
        confidence = "low"
        next_steps = ["补齐上列缺失的证据", "补齐后重跑一次综合分析"]
    else:
        conclusion = f"结论:可以推进。针对「{question}」,各 Agent 结论一致且证据充分。"
        confidence = "high"
        next_steps = ["按既定流程合入", "合入后观察线上登录成功率"]

    return Synthesis(conclusion=conclusion, evidence=evidence, next_steps=next_steps,
                     confidence=confidence)

_STRUCTURED_HANDLERS: dict[type[BaseModel], Any] = {
    IssueTriage: _issue_triage,
    PRReview: _pr_review,
    CIDebug: _ci_debug,
    SafetyAssessment: _safety_assessment,
    Plan: _plan,
    Observation: _observation,
    Synthesis: _synthesis,
}


def _structured_from_evidence(schema: type[BaseModel], messages: list[BaseMessage]) -> BaseModel:
    handler = _STRUCTURED_HANDLERS.get(schema)
    evidence = _extract_evidence(messages)
    if handler is None:  # 未知 schema:给出一个可解释的错误,而不是静默返回空
        raise NotImplementedError(f"确定性 Mock 未实现 schema: {schema.__name__}")
    return handler(evidence)


# --------------------------------------------------------------------------- 模型


class DeterministicChatModel(BaseChatModel):
    """确定性的假模型,但走真实的 BaseChatModel 协议。"""

    role: str | None = None
    tools: list[str] = []
    temperature: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "deterministic-mock"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"role": self.role, "tools": list(self.tools)}

    def bind_tools(self, tools, **kwargs) -> "DeterministicChatModel":  # noqa: ANN001
        names: list[str] = []
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None and isinstance(tool, dict):
                name = tool.get("name")
                if name is None and "function" in tool:
                    name = tool["function"].get("name")
            if name:
                names.append(str(name))
        return self.model_copy(update={"tools": names})

    def with_structured_output(self, schema: type[BaseModel], **kwargs) -> Runnable:  # noqa: ANN003
        if self.role in (None, AgentRole.CHAT.value):
            # chat_agent 不做结构化输出,这里显式拒绝,避免调用方以为能拿到对象
            raise NotImplementedError("DeterministicChatModel: chat_agent 不支持结构化输出")
        def _run(payload: Any) -> BaseModel:  # noqa: ANN401
            from app.rag.splitter import rough_token_count

            messages = _as_messages(payload)
            obj = _structured_from_evidence(schema, messages)
            # Mock 的结构化路径也要上报用量:否则工作流那条链路在 Mock 模式下
            # token 记账恒为 0,这块就没法在单测里验证。
            prompt = " ".join(str(m.content) for m in messages if isinstance(m.content, str))
            _record_usage(AIMessage(content=obj.model_dump_json(), usage_metadata={
                "input_tokens": rough_token_count(prompt),
                "output_tokens": rough_token_count(obj.model_dump_json()),
                "total_tokens": rough_token_count(prompt) + rough_token_count(obj.model_dump_json()),
            }))
            return obj

        return RunnableLambda(_run)

    def _generate(  # noqa: ANN001
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        role = self.role or parse_role(_system_text(messages)) or AgentRole.CHAT.value
        question = _last_human_text(messages)
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)

        # 已经拿到工具结果 → 收尾,不再调工具(这是循环的终止条件)
        if has_tool_result or not self.tools:
            return _chat_result(AIMessage(content=_compose_answer(role, messages)), messages)

        picked = _pick_tool(question, set(self.tools))
        if picked is None:
            return _chat_result(AIMessage(content=_compose_answer(role, messages)), messages)

        call = {"name": picked, "args": _args_for(picked, question), "id": f"call-{picked}"}
        return _chat_result(AIMessage(content="", tool_calls=[call]), messages)


def _system_text(messages: list[BaseMessage]) -> str:
    parts = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            parts.append(msg.content if isinstance(msg.content, str) else str(msg.content))
    return "\n".join(parts)


def _last_human_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


def _as_messages(payload: Any) -> list[BaseMessage]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, BaseMessage):
        return [payload]
    if isinstance(payload, dict):
        return [HumanMessage(json.dumps(payload, ensure_ascii=False))]
    return [HumanMessage(str(payload))]


# 结构化输出路径的用量收集器。
#
# 用 contextvar 装一个**可变列表**而不是标量:int 在子任务里 set 不会回传父任务,
# 但列表对象是共享引用 —— asyncio.gather 派生的子任务 append 进的是同一个列表。
# 工作流里各 Agent 是并发跑的,正是这个场景。
_usage_sink: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "devflow_usage_sink", default=None
)


@contextmanager
def collect_usage() -> Iterator[list[int]]:
    """收集这段代码里所有结构化模型调用上报的 token 用量。"""
    sink: list[int] = []
    token = _usage_sink.set(sink)
    try:
        yield sink
    finally:
        _usage_sink.reset(token)


def _record_usage(message: Any) -> None:
    sink = _usage_sink.get()
    if sink is None:
        return
    if (used := _usage_of_message(message)):
        sink.append(used)


def _usage_of_message(message: Any) -> int:
    meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return 0
    try:
        return int(meta.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def _chat_result(message: AIMessage, messages: list[BaseMessage] | None = None) -> ChatResult:
    """包成 ChatResult,并给 Mock 补上确定性的用量元数据。

    Mock 也要上报 usage:前端有 token 计数展示,如果真实模型上报、Mock 永远显示 0,
    这块在 Mock 模式下就没法验证。数值按输入/输出文本长度估算 ——
    与「Mock 是确定性的假模型」这一定位一致,不引入随机性。
    """
    if messages is not None:
        from app.rag.splitter import rough_token_count

        prompt = " ".join(str(m.content) for m in messages if isinstance(m.content, str))
        answer = message.content if isinstance(message.content, str) else ""
        prompt_tokens = rough_token_count(prompt)
        answer_tokens = rough_token_count(answer)
        message = message.model_copy(update={"usage_metadata": {
            "input_tokens": prompt_tokens,
            "output_tokens": answer_tokens,
            "total_tokens": prompt_tokens + answer_tokens,
        }})
    return ChatResult(generations=[ChatGeneration(message=message)])


# --------------------------------------------------------------------------- 工厂


def get_chat_model(*, tools: list | None = None, role: str | None = None) -> BaseChatModel:
    """按配置返回聊天模型。两条路径对外行为一致,调用方不需要分支。"""
    if settings.llm_mode == "openai":
        from langchain_openai import ChatOpenAI

        model: BaseChatModel = ChatOpenAI(
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.3,
            # 流式时也要带上用量,否则成本核算在流式路径上永远是 0
            stream_usage=True,
        )
    else:
        model = DeterministicChatModel(role=role)
    if tools:
        model = model.bind_tools(tools)
    return model


def _field_type(field: dict) -> str:
    if "$ref" in field:
        return field["$ref"].split("/")[-1]
    if "enum" in field:
        return "必须严格取以下之一: " + " / ".join(str(v) for v in field["enum"])
    kind = field.get("type")
    if kind == "array":
        return f"array<{_field_type(field.get('items') or {})}>"
    if "anyOf" in field:
        return " | ".join(_field_type(option) for option in field["anyOf"])
    return kind or "string"


def _render_props(spec: dict, indent: str = "") -> list[str]:
    lines: list[str] = []
    for name, field in (spec.get("properties") or {}).items():
        lines.append(f"{indent}- {name} ({_field_type(field)}):{field.get('description', '')}")
    return lines


def _json_instructions(schema: type[BaseModel]) -> str:
    """把 schema 渲染成给模型看的字段说明。

    json_mode 只保证「输出是 JSON」,不保证「字段对」;langchain 也不会替我们
    把 schema 写进 prompt。**必须连嵌套对象一起描述** ——
    只写顶层字段的话,像 Plan 这种 `{tasks: [{task_key, agent, ...}]}` 的结构,
    模型根本不知道每个 task 要哪些字段,解析必然失败(实测 12 个 missing 校验错误)。
    """
    spec = schema.model_json_schema()
    lines = [
        "你必须只输出一个 JSON 对象,不要输出任何解释文字,不要包 markdown 代码块。",
        "字段定义:",
    ]
    lines.extend(_render_props(spec))

    defs = spec.get("$defs") or {}
    if defs:
        lines.append("嵌套对象(出现在上面的字段里时,必须按下面的字段给出):")
        for name, sub in defs.items():
            if "enum" in sub:
                # 枚举型 $defs 没有 properties,必须把取值列出来,
                # 否则模型不知道 agent 只能填哪几个值
                allowed = " / ".join(str(v) for v in sub["enum"])
                lines.append(f"- {name}:必须严格取以下之一 → {allowed}")
                continue
            lines.append(f"- {name}:")
            lines.extend(_render_props(sub, indent="    "))

    required = spec.get("required") or []
    if required:
        lines.append("顶层必填:" + ", ".join(required))
    return "\n".join(lines)

def _JSON_INSTRUCTIONS_MODEL(payload: Any, instructions: str) -> list[BaseMessage]:
    """把字段说明并进第一条 system 消息;没有 system 就补一条。"""
    messages = _as_messages(payload)
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            content = message.content if isinstance(message.content, str) else str(message.content)
            messages[index] = SystemMessage(f"{content}\n\n{instructions}")
            return messages
    return [SystemMessage(instructions), *messages]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """从模型输出里抠出 JSON 主体(容忍 markdown 代码块与前后废话)。"""
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def _make_json_structured_model(schema: type[BaseModel], base) -> Runnable:  # noqa: ANN001
    """结构化输出执行器:json_object + 自己解析 + 一次修复重试。

    为什么不用 langchain 自带的 with_structured_output:
      - 默认的 json_schema response_format 被 DeepSeek 直接 400 拒绝;
      - function_calling 需要显式 tool_choice,而 thinking 模型不支持。

    为什么要修复重试:真实模型偶尔会「字段填了但填错」(例如把 confidence
    写成一段中文解释而不是 low/medium/high)。一次重试把校验错误回灌给模型,
    比直接抛异常更能反映模型的真实能力,也没有伪造任何数据。
    """
    instructions = _json_instructions(schema)
    model = base.bind(response_format={"type": "json_object"})

    async def _run(payload: Any, config: Any = None) -> BaseModel:  # noqa: ARG001
        messages = _JSON_INSTRUCTIONS_MODEL(payload, instructions)
        last_error: Exception | None = None
        # 3 次:实测真实模型偶发连续两次产出不合法 JSON,第三次通常能修回来
        for _ in range(3):
            response = await model.ainvoke(messages)
            _record_usage(response)
            text = response.content if isinstance(response.content, str) else str(response.content)
            try:
                return schema.model_validate_json(_extract_json(text))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                messages = [
                    *messages,
                    AIMessage(text),
                    HumanMessage(
                        f"上面的输出不是合法 JSON,或者字段不符合要求:{exc}\n"
                        "请重新只输出一个修正后的 JSON 对象,不要任何解释文字。"
                    ),
                ]
        raise ValueError(f"{schema.__name__} 结构化输出解析失败:{last_error}")

    return RunnableLambda(_run)

def get_structured_model(schema: type[BaseModel], *, role: str) -> Runnable:
    """返回可直接 ainvoke(messages) 得到 schema 实例的 Runnable。"""
    if settings.llm_mode == "openai":
        from langchain_openai import ChatOpenAI

        base = ChatOpenAI(
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.0,
        )
        # 结构化输出走 json_mode,不走 function_calling。两条实测原因:
        #  1) langchain 默认的 response_format=json_schema 被 DeepSeek 直接 400 拒绝;
        #  2) 该模型是 thinking 模型,显式 tool_choice 会被拒:
        #     "Thinking mode does not support this tool_choice"。
        # json_mode 只要求 response_format=json_object,并且需要我们自己把 schema 写进 prompt
        # (langchain 不会自动加),所以下面用 RunnableLambda 注入字段说明。
        return _make_json_structured_model(schema, base)
    return DeterministicChatModel(role=role).with_structured_output(schema)