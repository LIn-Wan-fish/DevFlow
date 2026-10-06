"""ActionDraft 生命周期:草稿 → 人工确认 → 执行 → 审计。

「模型没有直接执行写操作的通道」不是靠约定,是靠两层代码事实:
1. 工具注册表里只有 draft_action,没有 execute_action
2. 即便拿到草稿 id,也必须过 assert_can_write 才能推进状态
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ActionDraft, DraftStatus, Issue, Repo
from app.safety import audit, policy

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DraftStatus.PENDING.value: {DraftStatus.CONFIRMED.value, DraftStatus.REJECTED.value,
                                DraftStatus.EXPIRED.value},
    DraftStatus.CONFIRMED.value: {DraftStatus.EXECUTED.value, DraftStatus.FAILED.value},
    DraftStatus.REJECTED.value: set(),
    DraftStatus.EXECUTED.value: set(),
    DraftStatus.EXPIRED.value: set(),
    DraftStatus.FAILED.value: set(),
}


class InvalidTransition(Exception):
    """非法状态迁移。例如已 rejected 的草稿又去 confirm。"""


class DraftNotFound(Exception):
    pass


def _transition(draft: ActionDraft, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(draft.status, set())
    if target not in allowed:
        raise InvalidTransition(f"草稿 {draft.id} 无法从 {draft.status} 迁移到 {target}")


def create(
    db: Session,
    *,
    repo_id: int,
    run_id: int | None,
    action: str,
    target: str,
    payload: dict,
    role: str = "member",
) -> ActionDraft:
    """生成草稿。到这一步为止都不会产生任何副作用。"""
    if action not in policy.WRITE_ACTIONS:
        # 白名单外的动作连草稿都不给生成,并留一条 denied 审计
        audit.record(db, draft_id=None, action=action, target=target,
                     result=audit.DENIED, detail="动作不在写操作白名单内", actor_role=role)
        raise policy.PermissionDenied(f"动作 {action!r} 不在写操作白名单内")

    draft = ActionDraft(
        repo_id=repo_id,
        run_id=run_id,
        action=action,
        target=target,
        payload=payload,
        preview=_preview(action, target, payload),
        risk_level=policy.risk_level(action),
        status=DraftStatus.PENDING.value,
        requested_by_role=role,
    )
    db.add(draft)
    db.commit()
    return draft


def reject(db: Session, draft_id: int, *, role: str) -> ActionDraft:
    draft = _get(db, draft_id)
    _transition(draft, DraftStatus.REJECTED.value)
    draft.status = DraftStatus.REJECTED.value
    draft.decided_by_role = role
    draft.decided_at = datetime.now(UTC)
    db.commit()
    audit.record(db, draft_id=draft.id, action=draft.action, target=draft.target,
                 result=audit.REJECTED, detail="人工拒绝", actor_role=role)
    return draft


def confirm(db: Session, draft_id: int, *, role: str) -> ActionDraft:
    """人工确认后才执行。

    顺序不能颠倒:校验状态 → 校验权限 → 转 confirmed → 执行 → 落 executed + 审计。
    任何一步抛错都要把失败也写进审计。
    """
    draft = _get(db, draft_id)
    _transition(draft, DraftStatus.CONFIRMED.value)

    try:
        policy.assert_can_write(role, draft.action)
    except policy.PermissionDenied as exc:
        # 越权尝试同样留痕 —— 这是安全审计最有价值的一类记录
        audit.record(db, draft_id=draft.id, action=draft.action, target=draft.target,
                     result=audit.DENIED, detail=str(exc), actor_role=role)
        raise

    draft.status = DraftStatus.CONFIRMED.value
    draft.decided_by_role = role
    draft.decided_at = datetime.now(UTC)
    db.commit()

    try:
        _execute(db, draft)
    except Exception as exc:  # noqa: BLE001
        # 执行失败**不算成功**,但也绝不是「什么都没发生」:
        # 草稿标成 failed、审计留一条 failed —— 然后包成专用异常交给 API 层,
        # 让调用方看到「为什么失败」,而不是一个没有信息的 500。
        draft.status = DraftStatus.FAILED.value
        db.commit()
        audit.record(db, draft_id=draft.id, action=draft.action, target=draft.target,
                     result=audit.FAILED, detail=str(exc), actor_role=role)
        raise ExecutionFailed(str(exc)) from exc

    draft.status = DraftStatus.EXECUTED.value
    db.commit()
    audit.record(db, draft_id=draft.id, action=draft.action, target=draft.target,
                 result=audit.EXECUTED, detail=draft.preview, actor_role=role)
    return draft


def _get(db: Session, draft_id: int) -> ActionDraft:
    draft = db.get(ActionDraft, draft_id)
    if draft is None:
        raise DraftNotFound(f"草稿 {draft_id} 不存在")
    return draft


def _preview(action: str, target: str, payload: dict) -> str:
    if action == "comment_on_issue":
        return f"将在 {target} 下发表评论:{payload.get('body', '')[:120]}"
    if action == "add_labels":
        return f"将给 {target} 添加标签:{payload.get('labels', [])}"
    if action == "close_issue":
        return f"将关闭 {target}"
    if action == "reopen_issue":
        return f"将重新打开 {target}"
    return f"{action} → {target}"


class ExecutionFailed(RuntimeError):
    """写操作执行失败(上游拒绝、不可达、目标不存在等)。

    抛出前草稿已标为 failed、审计已留痕 —— 这个异常只负责把原因带到 API 层。
    """


def _execute(db: Session, draft: ActionDraft) -> None:
    """执行写操作。

    snapshot 模式写本地副本(数据库),不触碰任何外部系统 ——
    这样 Demo 离线也能演示完整的安全闸门,而且效果可验证。
    GitHub 模式下由 provider 走真实 REST(见 app/github/provider.py)。
    """
    from app.config import settings

    if settings.data_source == "github":
        from app.github.provider import execute_write_action

        execute_write_action(db, draft)
        return

    number = _target_number(draft.target)
    issue = db.query(Issue).filter_by(repo_id=draft.repo_id, number=number).one_or_none()
    if issue is None:
        raise LookupError(f"目标 {draft.target} 不存在")

    if draft.action == "comment_on_issue":
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        issue.body = f"{issue.body}\n\n---\n[DevFlow AI 评论 {stamp}]:{draft.payload.get('body', '')}"
    elif draft.action == "add_labels":
        merged = list(dict.fromkeys([*(issue.labels or []), *draft.payload.get("labels", [])]))
        issue.labels = merged
    elif draft.action == "close_issue":
        issue.state = "closed"
        issue.group = "closed"
    elif draft.action == "reopen_issue":
        issue.state = "open"
        issue.group = "unarchived"
    db.commit()


def _target_number(target: str) -> int:
    digits = "".join(ch for ch in target if ch.isdigit())
    if not digits:
        raise ValueError(f"无法从 {target!r} 解析出编号")
    return int(digits)


def repo_of(db: Session, repo_id: int) -> Repo | None:
    return db.get(Repo, repo_id)