"""把 Skill 注册成 Agent 可调用的工具。

章节 10.2 的标题就是「MCP 与 Skill **怎么进入 ChatAgent**」。
在此之前技能只是 `/api/skills` 里列得出来、点得动的一段声明 ——
Agent 调不到它,也就谈不上「扩展 ChatAgent 的能力」。这里补上那一跳。

两个处理细节:

1. **`repo_id` 由上下文注入,不进模型可见的参数表。**
   模型不需要(也不该)去猜仓库 ID —— 它就在 ToolContext 里。
   把它从 required 里摘掉,模型少一个必填项,也少一类填错的可能。
2. **含写操作的技能标记 is_write=True。**
   技能步骤里若出现内置的写工具(如 draft_action),整条技能就要过同一道安全闸门,
   不能让「包了一层封装」成为绕过人工确认的后门。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.skills.runtime import Skill, SkillFormatError, SkillRuntime
from app.tools.registry import REGISTRY, ToolContext, ToolResult, ToolSpec, execute, register

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
CONTEXT_INPUTS = {"repo_id"}   # 由上下文提供,不暴露给模型


def load_skills(directory: Path | None = None) -> list[Skill]:
    """读取目录下所有技能声明。坏文件跳过并记警告,不影响其他技能。"""
    base = directory or SKILLS_DIR
    if not base.exists():
        return []
    runtime = SkillRuntime()
    skills: list[Skill] = []
    for path in sorted(base.glob("*.yaml")):
        try:
            skills.append(runtime.load(path))
        except (SkillFormatError, yaml.YAMLError) as exc:
            logger.warning("技能文件 %s 解析失败,已跳过:%s", path.name, exc)
    return skills


def _exposed_parameters(skill: Skill) -> dict:
    """给模型看的参数表:摘掉上下文注入的那些。"""
    schema = dict(skill.input_schema or {})
    properties = {k: v for k, v in (schema.get("properties") or {}).items()
                  if k not in CONTEXT_INPUTS}
    required = [k for k in (schema.get("required") or []) if k not in CONTEXT_INPUTS]
    return {"type": "object", "properties": properties, "required": required}


def _is_write_skill(skill: Skill) -> bool:
    return any(REGISTRY.get(step.get("tool"), None)
               and REGISTRY[step["tool"]].is_write for step in skill.steps)


def _make_handler(runtime: SkillRuntime, skill: Skill):  # noqa: ANN202
    async def handler(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        async def executor(tool: str, args: dict) -> Any:
            params = dict(args or {})
            repo_id = int(params.pop("repo_id", ctx.repo_id) or ctx.repo_id)
            # 复用调用方的会话与身份:技能不该拿到比调用者更大的权限
            sub = ToolContext(db=ctx.db, repo_id=repo_id, role=ctx.role,
                              run_id=ctx.run_id, session_id=ctx.session_id,
                              emit=ctx.emit, cancel=ctx.cancel)
            return await execute(tool, params, sub)

        # repo_id 已从模型可见参数里摘掉,这里必须由上下文补回来 ——
        # 否则 validate 会因为它"必填但缺失"直接拒绝,模型怎么调都失败。
        inputs = {**kwargs, "repo_id": kwargs.get("repo_id") or ctx.repo_id}
        result = await runtime.run(skill, inputs, executor=executor)
        steps = result["results"]
        summary = f"技能 {skill.name} 执行了 {len(steps)} 步:" + "; ".join(
            f"{s['tool']}→{getattr(s['result'], 'summary', s['result'])}" for s in steps
        )
        return ToolResult(
            tool=f"skill__{skill.name}",
            summary=summary[:400],
            data={"skill": skill.name, "steps_executed": len(steps),
                  "steps": [{"tool": s["tool"],
                             "summary": getattr(s["result"], "summary", str(s["result"]))}
                            for s in steps]},
            evidence_refs=[f"skill:{skill.name}"],
        )

    return handler


def install_skill_tools(directory: Path | None = None) -> list[str]:
    """把技能注册成 Agent 工具,返回本次注册的名字。已注册过的跳过。

    **必须在 MCP 之后调用**:技能是否算写操作要查工具表,而工具表里
    刚刚才被 MCP 补进外部工具。
    """
    runtime = SkillRuntime()
    installed: list[str] = []
    for skill in load_skills(directory):
        name = f"skill__{skill.name}"
        if name in REGISTRY:
            continue
        register(ToolSpec(
            name=name,
            description=skill.description or f"技能 {skill.name}",
            parameters=_exposed_parameters(skill),
            handler=_make_handler(runtime, skill),
            is_write=_is_write_skill(skill),
        ))
        installed.append(name)

    if installed:
        logger.info("已接入 %s 个技能:%s", len(installed), installed)
    return installed