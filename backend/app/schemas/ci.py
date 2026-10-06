from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CIDebug(BaseModel):
    """CI 排障结果。CIDebugAgent 的输出契约。"""

    root_cause: str = Field(description="根因;日志缺失时必须明说「未找到」,禁止编造")
    error_blocks: list[str] = Field(description="日志中的关键错误片段,原文摘录")
    fix_steps: list[str] = Field(description="具体修复步骤")
    related_files: list[str] = Field(description="相关文件")
    confidence: Confidence = Field(description="结论置信度")