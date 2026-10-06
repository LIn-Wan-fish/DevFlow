"""专用 Agent 基类。

三个约束写进结构里,而不是靠自觉:
1. 每个 Agent 的 Prompt 自己一份(不做万能 Prompt)
2. 每个 Agent 的输入证据自己一份(gather_evidence 由子类实现)
3. 每个 Agent 的输出结构自己一份(schema 由子类声明)
这样它们才能被单独测、单独调,出问题也能定位到具体是哪一个。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.llm import get_structured_model
from app.core.prompts.roles import AgentRole


class SpecialistAgent(ABC):
    role: AgentRole
    schema: type[BaseModel]

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def gather_evidence(self, db: Session, **kwargs) -> dict: ...

    async def run(self, db: Session, **kwargs) -> BaseModel:
        evidence = self.gather_evidence(db, **kwargs)
        model = get_structured_model(self.schema, role=self.role.value)
        messages = [
            SystemMessage(self.system_prompt),
            HumanMessage(_dump(evidence)),
        ]
        return await model.ainvoke(messages)


def _dump(evidence: dict) -> str:
    import json

    return json.dumps(evidence, ensure_ascii=False, default=str)