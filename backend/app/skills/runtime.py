"""最小 Skill Runtime:把稳定流程声明成可复用、可校验的技能。

不做的:marketplace、版本管理、依赖解析。
要证明的只有一件事:一段研发流程能被声明出来,并且入参不合法时会被拦下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

PLACEHOLDER = "{{ %s }}"


class SkillInputError(Exception):
    pass


class SkillFormatError(Exception):
    pass


@dataclass
class Skill:
    name: str
    description: str
    steps: list[dict]
    input_schema: dict = field(default_factory=dict)


class SkillRuntime:
    SkillInputError = SkillInputError

    def load(self, path: str | Path) -> Skill:
        file = Path(path)
        if not file.exists():
            raise SkillFormatError(f"技能文件不存在: {file}")
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        if not raw.get("name") or not raw.get("steps"):
            raise SkillFormatError("技能必须包含 name 与 steps")
        return Skill(
            name=raw["name"],
            description=raw.get("description", ""),
            steps=list(raw["steps"]),
            input_schema=raw.get("input_schema", {}),
        )

    def validate(self, skill: Skill, inputs: dict) -> None:
        schema = skill.input_schema or {}
        for key in schema.get("required", []):
            if key not in inputs:
                raise SkillInputError(f"技能 {skill.name} 缺少必填参数 {key}")
        for key, spec in (schema.get("properties") or {}).items():
            if key in inputs and spec.get("type") == "integer" and not isinstance(inputs[key], int):
                raise SkillInputError(f"参数 {key} 应为整数")

    async def run(
        self,
        skill: Skill,
        inputs: dict,
        *,
        executor: Callable[[str, dict], Any] | None = None,
    ) -> dict:
        """按声明顺序执行步骤。

        **异步**:技能要被 Agent 当工具调用,而 Agent 的工具处理器本身是 async 的 ——
        同步版本只能用 asyncio.run,那会在已有事件循环里直接抛错。
        """
        self.validate(skill, inputs)
        executor = executor or self._default_executor
        results: list[dict] = []
        for step in skill.steps:
            tool = step.get("tool")
            if not tool:
                raise SkillFormatError("步骤缺少 tool 字段")
            args = {k: self._resolve(v, inputs) for k, v in (step.get("args") or {}).items()}
            results.append({"tool": tool, "args": args, "result": await executor(tool, args)})
        return {"skill": skill.name, "steps_executed": len(results), "results": results}

    @staticmethod
    def _resolve(value: Any, inputs: dict) -> Any:
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            key = value.strip("{} ").strip()
            return inputs.get(key)
        return value

    @staticmethod
    async def _default_executor(tool: str, args: dict) -> Any:
        from app.db.session import SessionLocal
        from app.tools.registry import ToolContext, execute

        with SessionLocal() as db:
            repo_id = int(args.pop("repo_id", 1))
            ctx = ToolContext(db=db, repo_id=repo_id)
            return await execute(tool, args, ctx)