"""ChatAgent:原生 Tool Calling 循环 + 执行约束。

三条约束对应原文亮点 3,每条都有独立测试:
1. 最大步数(max_steps):超限停止并交付已有结论,不静默失败
2. 重复调用拦截:同一 (工具, 参数) 第 2 次出现即停 —— 这是原文明确要求的
3. 工具错误回灌:异常转成 ToolMessage 让模型换路子,连续错误达上限才停

所有停止原因都会带回 stop_reason 并落库,这样「答不出来」才能被追溯。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm import get_chat_model
from app.core.prompts.chat import CHAT_SYSTEM
from app.observability.events import emit_event
from app.core.workflow_rules import needs_workflow, pick_tool, tool_args, wants_draft
from app.tools.registry import REGISTRY, ToolContext, as_langchain_tools, execute

logger = logging.getLogger(__name__)

REPEAT_LIMIT = 2
MAX_CONSECUTIVE_TOOL_ERRORS = 3


def _usage_of(message: Any) -> int:
    """取一条消息上报的 token 用量。

    拿不到就返回 0 —— 宁可显示「未上报」,也不要用字数估算冒充真实用量。
    """
    meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return 0
    try:
        return int(meta.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class ToolCallRecord:
    tool: str
    args: dict
    summary: str = ""
    error: str | None = None
    step: int = 0
    # 工具返回的原始结构化结果,API 层落轨迹时要用(如工作流的任务明细)
    data: dict = field(default_factory=dict)


@dataclass
class AgentOutcome:
    answer: str
    stop_reason: str
    steps: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    drafts: list[dict] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    # 模型**真实回报**的用量合计;拿不到就是 0,不用估算值冒充
    total_tokens: int = 0


def _canonical_args(args: dict) -> str:
    return json.dumps(args or {}, sort_keys=True, ensure_ascii=False)


class ChatAgent:
    def __init__(self, *, force_tools: list[str] | None = None) -> None:
        # 测试钩子:强制每步返回指定工具(按步数轮换)。
        # 生产路径永远传 None —— 用它来构造「模型一直要调工具」这类场景。
        self.force_tools = force_tools
        self._total_tokens = 0

    async def _stream_message(
        self, model: Any, messages: list[BaseMessage], emit: Any, step: int,
        cancel: asyncio.Event | None = None,
    ) -> Any:
        """调用模型并把增量 token 推给前端,返回**合并后的完整消息**。

        为什么要流式:真实 thinking 模型生成一段结论要几十秒,
        没有增量输出的话用户只能盯着「正在取证与分析…」干等。

        失败处理:如果模型不支持流式(或者还没吐任何内容就失败),退回一次性调用;
        但**已经吐出去的内容不能悄悄重发**,否则用户会看到重复段落,所以那种情况直接抛出。
        """
        chunks: list[Any] = []
        streamed = False
        usage = 0
        try:
            async for chunk in model.astream(messages):
                # 在 token 之间检查取消:一次生成可能持续几十秒,
                # 只在调用前后检查的话,用户点了停止还得等它把这段话写完
                if cancel is not None and cancel.is_set():
                    break
                chunks.append(chunk)
                if (u := _usage_of(chunk)):
                    usage = u
                delta = chunk.content if isinstance(chunk.content, str) else ""
                if delta:
                    streamed = True
                    await emit_event(emit, "token", {"delta": delta, "step": step})
        except Exception:  # noqa: BLE001
            if streamed:
                raise
            logger.warning("模型不支持流式输出,退回一次性调用", exc_info=True)
            message = await model.ainvoke(messages)
            return message, _usage_of(message)

        if not chunks:
            if cancel is not None and cancel.is_set():
                # 一开头就被取消:不要再发一次没人接收的请求
                return AIMessage(content=""), 0
            message = await model.ainvoke(messages)
            return message, _usage_of(message)

        merged = chunks[0]
        for chunk in chunks[1:]:
            merged = merged + chunk
        return merged, usage

    async def run(
        self,
        db: Session,
        *,
        repo_id: int,
        question: str,
        history: list[BaseMessage] | None = None,
        emit: Any = None,
        role: str = "member",
        run_id: int | None = None,
        session_id: int | None = None,
        cancel: asyncio.Event | None = None,
    ) -> AgentOutcome:
        async def default_emit(kind: str, data: dict) -> None:  # noqa: ANN001
            return None

        emit = emit or default_emit
        ctx = ToolContext(db=db, repo_id=repo_id, role=role, run_id=run_id,
                          session_id=session_id, emit=emit, cancel=cancel)

        model = get_chat_model(tools=as_langchain_tools(), role="chat_agent")
        messages: list[BaseMessage] = [
            SystemMessage(CHAT_SYSTEM),
            *(history or []),
            HumanMessage(question),
        ]

        seen: Counter[tuple[str, str]] = Counter()
        consecutive_errors = 0
        records: list[ToolCallRecord] = []
        citations: list[dict] = []
        drafts: list[dict] = []

        # 架构决定:复杂问题必须进多 Agent 工作流,不交给模型自由裁量。
        # 实测(deepseek-flash)真实模型会直接连调几个工具,导致 Planner/Observer/
        # Synthesis 这套多 Agent 能力永远不触发 —— 那样它就只是文档里的摆设。
        # 所以这里按同一套规则预路由,和 Mock 模式行为一致。
        if not self.force_tools and needs_workflow(question) and "run_workflow" in REGISTRY:
            if cancel is not None and cancel.is_set():
                # 一进来就被取消:连规划都不要发起
                return self._finish("已中断:尚未开始分析。", records, citations, drafts,
                                    "cancelled", 0)
            args = {"question": question}
            await emit_event(emit, "tool_call", {"tool": "run_workflow", "args": args, "step": 1})
            result = await execute("run_workflow", args, ctx)
            records.append(ToolCallRecord(tool="run_workflow", args=args,
                                          summary=result.summary, step=1, data=result.data))
            await emit_event(emit, "tool_result", {
                "tool": "run_workflow", "summary": result.summary,
                "evidence_refs": result.evidence_refs, "step": 1})
            # 直接交付 Synthesis 的结论,不再让模型转述一遍:
            # 那段结论是「正面回应冲突 + 列出证据 + 给下一步」的产物,
            # 转述一次就可能把对冲突的回应丢掉(实测真实模型确实丢了)。
            conclusion = str(result.data.get("conclusion") or result.summary)
            # 工作流可能跑到一半被取消 —— 这时不能报 completed,
            # 否则一条被中断的运行会在轨迹里谎报成功(实测踩到过)。
            stop = "cancelled" if (cancel is not None and cancel.is_set()) else "completed"
            return self._finish(conclusion, records, citations, drafts, stop, 1)

        # 写操作必须生成草稿 —— 同样是系统级要求,不能听凭模型裁量。
        # 实测真实模型有时会跳过 draft_action、只给一段文字建议,
        # 那样「草稿 + 人工确认」这道闸门根本没被触发。
        if not self.force_tools and wants_draft(question) and "draft_action" in REGISTRY:
            args = tool_args("draft_action", question)
            await emit_event(emit, "tool_call", {"tool": "draft_action", "args": args, "step": 1})
            try:
                result = await execute("draft_action", args, ctx)
                records.append(ToolCallRecord(tool="draft_action", args=args,
                                              summary=result.summary, step=1, data=result.data))
                drafts.append(result.data)
                await emit_event(emit, "draft", result.data)
                await emit_event(emit, "tool_result", {
                    "tool": "draft_action", "summary": result.summary,
                    "evidence_refs": result.evidence_refs, "step": 1})
                messages.append(HumanMessage(
                    "系统已按写操作闸门生成草稿,内容如下。请向用户说明草稿内容,"
                    "并强调「必须人工确认后才会执行」,不要说已经执行:\n" + result.as_json()))
            except Exception as exc:  # noqa: BLE001
                records.append(ToolCallRecord(tool="draft_action", args=args,
                                              error=str(exc), step=1))
                await emit_event(emit, "tool_result",
                                 {"tool": "draft_action", "error": str(exc), "step": 1})
            composed, used = await self._stream_message(model, messages, emit, 1, cancel=cancel)
            self._total_tokens += used
            text = composed.content if isinstance(composed.content, str) else ""
            fallback = records[-1].summary or records[-1].error or ""
            return self._finish(text or fallback, records, citations, drafts,
                                "completed", 1)

        for step in range(1, settings.max_agent_steps + 1):
            # 客户端断开时在这里收手:继续跑等于继续烧模型调用,而结果没人接收
            if cancel is not None and cancel.is_set():
                return self._finish(self._partial(records), records, citations, drafts,
                                    "cancelled", step - 1)

            response, used = await self._stream_message(model, messages, emit, step, cancel=cancel)
            self._total_tokens += used
            if self.force_tools:
                name = self.force_tools[(step - 1) % len(self.force_tools)]
                response = AIMessage(content="", tool_calls=[
                    {"name": name, "args": {}, "id": f"forced-{step}"}])

            if not response.tool_calls:
                # 实测(deepseek-flash)真实模型会不调任何工具、直接凭印象作答。
                # 而「回答前先取证」是这个系统的硬要求,不是建议,所以系统代它取证。
                #
                # 注意实现方式:工具结果作为**用户侧上下文**追加,而不是伪造一条
                # assistant tool_calls 消息 —— DeepSeek 的 thinking 模式要求 assistant
                # 轮必须把 reasoning_content 一起带回去,伪造的轮次没有这个字段,
                # 下一次请求会被直接 400 拒绝。
                if step == 1 and not self.force_tools:
                    forced = pick_tool(question, set(REGISTRY), allow_fallback=False)
                    if forced:
                        args = tool_args(forced, question)
                        await emit_event(emit, "tool_call",
                                         {"tool": forced, "args": args, "step": step,
                                          "forced": True})
                        try:
                            result = await execute(forced, args, ctx)
                            records.append(ToolCallRecord(tool=forced, args=args,
                                                          summary=result.summary, step=step,
                                                          data=result.data))
                            citations.extend(result.citations)
                            if result.data.get("draft_id"):
                                drafts.append(result.data)
                                await emit_event(emit, "draft", result.data)
                            await emit_event(emit, "tool_result", {
                                "tool": forced, "summary": result.summary,
                                "evidence_refs": result.evidence_refs, "step": step,
                                "forced": True})
                            messages.append(HumanMessage(
                                "系统已自动取证。以下是与本问题相关的工具执行结果,"
                                "请只依据它作答,不要凭印象补充:\n" + result.as_json()))
                        except Exception as exc:  # noqa: BLE001
                            records.append(ToolCallRecord(tool=forced, args=args,
                                                          error=str(exc), step=step))
                            await emit_event(emit, "tool_result",
                                             {"tool": forced, "error": str(exc), "step": step})
                        continue
                if not response.tool_calls:
                    return self._finish(response.content, records, citations, drafts,
                                        "completed", step)

            messages.append(response)
            for call in response.tool_calls:
                name = call["name"]
                args = call.get("args") or {}
                key = (name, _canonical_args(args))
                seen[key] += 1
                if seen[key] >= REPEAT_LIMIT:
                    # 原文要求的「限制重复调用」:同一工具同一参数第二次出现即停
                    return self._finish(self._partial(records), records, citations, drafts,
                                        "repeated_tool_call", step)

                await emit_event(emit, "tool_call", {"tool": name, "args": args, "step": step})
                try:
                    result = await execute(name, args, ctx)
                except Exception as exc:  # noqa: BLE001
                    consecutive_errors += 1
                    records.append(ToolCallRecord(tool=name, args=args,
                                                  error=f"{type(exc).__name__}: {exc}", step=step))
                    await emit_event(emit, "tool_result",
                                     {"tool": name, "error": str(exc), "step": step})
                    # 错误回灌给模型,让它有机会换条路子,而不是直接崩
                    messages.append(ToolMessage(
                        json.dumps({"error": str(exc)}, ensure_ascii=False),
                        tool_call_id=call.get("id", name)))
                    if consecutive_errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
                        return self._finish(self._partial(records), records, citations, drafts,
                                            "tool_error_limit", step)
                    continue

                consecutive_errors = 0
                records.append(ToolCallRecord(tool=name, args=args, summary=result.summary,
                                              step=step, data=result.data))
                citations.extend(result.citations)
                if result.data.get("draft_id"):
                    drafts.append(result.data)
                    await emit_event(emit, "draft", result.data)
                await emit_event(emit, "tool_result", {
                    "tool": name, "summary": result.summary,
                    "evidence_refs": result.evidence_refs, "step": step,
                })
                messages.append(ToolMessage(result.as_json(),
                                            tool_call_id=call.get("id", name)))

        return self._finish(self._partial(records), records, citations, drafts,
                            "max_steps", settings.max_agent_steps)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _partial(records: list[ToolCallRecord]) -> str:
        if not records:
            return "没有收集到任何可用信息。"
        lines = ["已达到执行上限,以下是根据已收集信息得到的初步结果:"]
        for record in records:
            if record.error:
                lines.append(f"- {record.tool}:调用失败({record.error})")
            else:
                lines.append(f"- {record.tool}:{record.summary}")
        return "\n".join(lines)

    def _finish(self, answer: str | Any, records: list[ToolCallRecord], citations: list[dict],
                drafts: list[dict], stop_reason: str, steps: int) -> AgentOutcome:
        text = answer if isinstance(answer, str) else str(answer or "")
        return AgentOutcome(
            answer=text or "未能形成结论。",
            stop_reason=stop_reason,
            steps=steps,
            tool_calls=records,
            citations=citations,
            drafts=drafts,
            next_steps=[],
            total_tokens=self._total_tokens,
        )