from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, description="会话 ID,同一会话多轮复用")
    repo_id: int = Field(description="当前仓库")
    message: str = Field(min_length=1, description="用户本轮消息")
    # 注意:这里**没有** role 字段。角色由服务端从请求头解析(见 app/api/auth.py),
    # 不接受请求体自称,否则授权就没有意义。


class ChatDone(BaseModel):
    run_id: int
    answer: str
    citations: list[dict] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    stop_reason: str
    steps: int
    drafts: list[dict] = Field(default_factory=list)