"""Skill Runtime 的运行时入口。

技能是「把稳定的操作流程声明成可复用能力」,只写在代码里没有意义 ——
必须能被列出来、能被跑起来,才算真的接进来了。
"""

from __future__ import annotations

from pathlib import Path

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel

from app.db.session import get_db
from app.skills.runtime import SkillFormatError, SkillInputError, SkillRuntime
from app.tools.registry import REGISTRY, ToolContext, execute
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/skills", tags=["Skill 技能"])

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills" / "skills"


class SkillRunRequest(BaseModel):
    inputs: dict = {}


def _runtime() -> SkillRuntime:
    return SkillRuntime()


def _skill_paths() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(SKILLS_DIR.glob("*.yaml"))


@router.get("", summary="列出技能(含是否已注册进工具表)")
def list_skills() -> dict:
    runtime = _runtime()
    skills = []
    for path in _skill_paths():
        try:
            skill = runtime.load(path)
        except SkillFormatError:
            continue
        skills.append({
            "name": skill.name,
            "description": skill.description,
            "steps": [step.get("tool") for step in skill.steps],
            "input_schema": skill.input_schema,
            # 关键:能列出来 ≠ Agent 调得到。章节 10.2 讲的是
            # 「Skill 怎么进入 ChatAgent」,所以如实报告它有没有真的进工具表。
            "registered": f"skill__{skill.name}" in REGISTRY,
        })
    return {"skills": skills}


def _executor_for(db: Session):
    """技能步骤统一走请求级会话,保证接口看到的就是当前库里的数据。"""

    async def run(tool: str, args: dict):
        params = dict(args or {})
        repo_id = int(params.pop("repo_id", 1))
        ctx = ToolContext(db=db, repo_id=repo_id)
        return await execute(tool, params, ctx)

    return run


@router.post("/{name}/run", summary="执行技能(按声明顺序跑步骤)")
async def run_skill(name: str = PathParam(..., description="技能名,见 /api/skills"), body: SkillRunRequest | None = None,
                    db: Session = Depends(get_db)) -> dict:
    runtime = _runtime()
    target = None
    for path in _skill_paths():
        try:
            skill = runtime.load(path)
        except SkillFormatError:
            continue
        if skill.name == name:
            target = skill
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"技能 {name} 不存在")

    try:
        result = await runtime.run(
            target,
            (body.inputs if body else {}) or {},
            executor=_executor_for(db),
        )
    except SkillInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "skill": result["skill"],
        "steps_executed": result["steps_executed"],
        "steps": [
            {"tool": step["tool"], "args": step["args"],
             "summary": getattr(step["result"], "summary", str(step["result"]))}
            for step in result["results"]
        ],
    }