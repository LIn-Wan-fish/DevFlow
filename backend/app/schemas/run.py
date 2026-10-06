from typing import Any

from pydantic import BaseModel


class RunTraceOut(BaseModel):
    agent_run: dict[str, Any] = {}
    workflow_runs: list[dict] = []
    task_runs: list[dict] = []
    tool_calls: list[dict] = []