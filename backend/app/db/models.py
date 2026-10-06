"""ORM 模型。

设计约定:
- 只用可移植类型(Integer/String/Text/Boolean/DateTime/JSON),这样单测能跑 SQLite in-memory。
- 状态字段用 @validates 在 Python 侧校验,非法值在赋值时立刻 ValueError,
  而不是等到 flush 时抛一个和业务无关的 LookupError。
- 所有 *_runs 表必须能按 agent_run_id 串起来,这是「留痕迹」的基础。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- 状态枚举


class IssueState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class PRState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class DraftStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class MemoryStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class _ValidatedStr:
    """按枚举校验字符串列。非法值在赋值时立刻抛 ValueError。"""

    _enum: type[StrEnum]

    @validates("status")
    def _validate_status(self, key: str, value):  # noqa: D102
        allowed = {m.value for m in self._enum}
        if value not in allowed:
            raise ValueError(f"{key} 非法值 {value!r},只允许 {sorted(allowed)}")
        return value


# --------------------------------------------------------------------------- 仓库与会话


class Repo(Base, TimestampMixin):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    workspace_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_github: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"))
    title: Mapped[str] = mapped_column(String(200), default="默认会话")

    messages: Mapped[list[Message]] = relationship(back_populates="session")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)

    session: Mapped[Session] = relationship(back_populates="messages")


# --------------------------------------------------------------------------- 研发数据


class Issue(Base, TimestampMixin):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_issue_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    # BigInteger:GitHub 的编号体系迟早会超过 int32 上限(实测 Actions run id 已到 3e10)
    number: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default=IssueState.OPEN.value)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(120), default="")
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 右栏分组计数用:unarchived/discussing/pending_decision/handled/rejected/closed
    group: Mapped[str] = mapped_column(String(30), default="unarchived")

    @validates("state")
    def _v_state(self, key, value):
        allowed = {m.value for m in IssueState}
        if value not in allowed:
            raise ValueError(f"issue.state 非法值 {value!r}")
        return value


class PullRequest(Base, TimestampMixin):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_pr_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    number: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default=PRState.OPEN.value)
    head_ref: Mapped[str] = mapped_column(String(200), default="")
    base_ref: Mapped[str] = mapped_column(String(200), default="main")
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    merged: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[str] = mapped_column(String(120), default="")
    related_issues: Mapped[list] = mapped_column(JSON, default=list)
    reviews: Mapped[list] = mapped_column(JSON, default=list)

    files: Mapped[list[PrFile]] = relationship(back_populates="pr",
                                                cascade="all, delete-orphan")


class PrFile(Base, TimestampMixin):
    __tablename__ = "pr_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pr_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    patch_summary: Mapped[str] = mapped_column(Text, default="")
    # 由 app.safety.policy.is_high_risk_path 判定后写入,不散落在 Prompt 里
    is_high_risk: Mapped[bool] = mapped_column(Boolean, default=False)

    pr: Mapped[PullRequest] = relationship(back_populates="files")


class CiRun(Base, TimestampMixin):
    __tablename__ = "ci_runs"
    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_ci_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    # GitHub Actions 的 run id 是 64 位(实测 30158064097),INTEGER 直接溢出
    number: Mapped[int] = mapped_column(BigInteger)
    workflow: Mapped[str] = mapped_column(String(200), default="CI")
    branch: Mapped[str] = mapped_column(String(200), default="main")
    status: Mapped[str] = mapped_column(String(30), default="completed")
    conclusion: Mapped[str] = mapped_column(String(30), default="success")
    commit_sha: Mapped[str] = mapped_column(String(80), default="")
    commit_message: Mapped[str] = mapped_column(String(400), default="")
    log_path: Mapped[str] = mapped_column(String(500), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("repo_id", "path", name="uq_doc_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(400), default="")
    doc_type: Mapped[str] = mapped_column(String(40), default="markdown")
    version: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    heading_path: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # 与 Milvus 主键一一对应;删文档要同时清两处
    milvus_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


# --------------------------------------------------------------------------- 记忆


class MemoryCandidate(Base, TimestampMixin):
    __tablename__ = "memory_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=0.5)
    status: Mapped[str] = mapped_column(String(20), default=MemoryStatus.PENDING.value)


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    approved_by: Mapped[str] = mapped_column(String(60), default="")
    milvus_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# --------------------------------------------------------------------------- 安全


class ActionDraft(Base, TimestampMixin, _ValidatedStr):
    __tablename__ = "action_drafts"

    _enum = DraftStatus

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    preview: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    status: Mapped[str] = mapped_column(String(20), default=DraftStatus.PENDING.value)
    requested_by_role: Mapped[str] = mapped_column(String(30), default="member")
    decided_by_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120), default="")
    result: Mapped[str] = mapped_column(String(30))  # executed / rejected / denied / failed
    detail: Mapped[str] = mapped_column(Text, default="")
    actor_role: Mapped[str] = mapped_column(String(30), default="")


# --------------------------------------------------------------------------- 运行轨迹


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    task_key: Mapped[str] = mapped_column(String(40))
    agent: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING.value)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    task_run_id: Mapped[int | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- 评测


class EvalRun(Base, TimestampMixin):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalCase(Base, TimestampMixin):
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), index=True)
    case_key: Mapped[str] = mapped_column(String(80))
    question: Mapped[str] = mapped_column(Text)
    expected: Mapped[dict] = mapped_column(JSON, default=dict)
    actual: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_results: Mapped[list] = mapped_column(JSON, default=list)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)

class ReportTrigger(StrEnum):
    AUTO = "auto"      # 调度器自动生成
    MANUAL = "manual"  # 人工点一下生成


class WeeklyReport(Base, TimestampMixin):
    """自动周报的落库形态。

    周报正文同时**回写知识库**(documents + 文件),这样下一轮索引后,
    团队的历史产出就变成可检索的资产 —— 而不只是发出去就没了。
    """

    __tablename__ = "weekly_reports"
    # 同一个仓库、同一个周期只留一份:调度器靠它做幂等,不会重复烧一遍
    __table_args__ = (UniqueConstraint("repo_id", "period_key", name="uq_report_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    period_key: Mapped[str] = mapped_column(String(20))    # 例如 2026-W41
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(20), default=ReportTrigger.AUTO.value)
    path: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    merged_prs: Mapped[int] = mapped_column(Integer, default=0)
    failed_ci: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class FindingStatus(StrEnum):
    """发现的成熟度。对应 Plastic 的「变更集 vs 搁置集」。"""

    TENTATIVE = "tentative"      # 搁置集:还没定论,别的 Agent 可以取用或接手
    CONFIRMED = "confirmed"      # 已确认
    SUPERSEDED = "superseded"    # 被后续发现取代(不是删掉,是留痕)


class AgentFinding(Base, TimestampMixin):
    """一个 Agent 的**变更集**:原子、不可变、带作者。

    为什么要有这张表 —— 借鉴 Unity Version Control(Plastic SCM)的协作模型:

    它的协作之所以成立,不是"大家能同时改",而是三件事:
      1. 有一个所有协作者都读写的**共享仓库**
      2. 改动是**带作者的最小单元**(变更集),而不是一团糊涂账
      3. **冲突是一等公民**,被显式记录和展示,而不是悄悄吞掉

    我们原先一条都不满足:每个 Agent 把结果交回 synthesis 就完了,
    彼此看不见、也无法质疑 —— 那是流水线,不是协作。

    **不可变**由 before_update 事件强制(见本文件末尾的监听器):
    要修正只能追加一条新发现并用 `supersedes_id` 指向旧的。
    协作历史如果可以被就地改写,它就不再是历史。
    """

    __tablename__ = "agent_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    # 哪个子任务产生的(可空:observer/synthesis 也会写发现)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    author: Mapped[str] = mapped_column(String(60))          # Agent 名,如 ci_debug
    topic: Mapped[str] = mapped_column(String(200), index=True)  # 调查主题(也是锁的键)
    conclusion: Mapped[str] = mapped_column(Text)            # 一句话结论
    # 依据:工具返回、引用、原始片段 —— 结构化存,便于追溯「这个结论从哪来」
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default=FindingStatus.CONFIRMED.value)
    # 引用了哪些其他发现(协作图就是靠它画出来的)
    references: Mapped[list] = mapped_column(JSON, default=list)
    supersedes_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

# --------------------------------------------------------------------------- 不可变性

@event.listens_for(AgentFinding, "before_update")
def _forbid_finding_update(mapper, connection, target) -> None:  # noqa: ANN001, ARG001
    """禁止就地修改一条发现。

    **写在 ORM 层而不是只靠约定**:「不可变」如果只是口头约定,迟早有人图省事
    直接改一行,协作历史就烂了。要修正只能追加新发现 + `supersedes_id`,
    这样「谁在什么时候推翻了什么」才是可追溯的。
    """
    raise ValueError(
        "AgentFinding 不可修改。要修正请追加一条新发现,并用 supersedes_id 指向它。"
    )