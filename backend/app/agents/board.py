"""共享发现板 —— 多 Agent 协作的「中央仓库」。

借鉴 Unity Version Control(Plastic SCM)的协作模型。它的协作之所以成立,
不是"大家能同时改",而是三件事:

  1. 有一个所有协作者都读写的**共享仓库**
  2. 改动是**带作者的最小单元**(变更集),而不是一团糊涂账
  3. **冲突是一等公民**,被显式记录和展示,而不是悄悄吞掉

对应到这里:
  - 共享仓库   -> `agent_findings` 表(所有 Agent 读写同一块板)
  - 变更集     -> 一条 Finding:作者 + 结论 + 依据 + 置信度 + 时间,落库不可改
  - 搁置集     -> `status=tentative`:还没定论,别的 Agent 可以取用或接手
  - 互斥锁     -> `claim()`:开工前认领主题,拦住重复调查(重复调查 = 重复烧钱)
  - 合并链接   -> `references` / `supersedes_id`:谁读了谁、谁推翻了谁

**为什么锁和发现板放在一起**:它们服务同一件事 —— 「谁负责调查什么」。
Plastic 里 checkout 同时表达"我要改"和"别人别改";这里 `claim` 是同一层意思。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.db import models as m

logger = logging.getLogger(__name__)

# 认领主题的存活时间。够一次调查跑完,又不至于让崩溃的 Agent 长期占着。
CLAIM_TTL_SECONDS = 300


def normalize_topic(topic: str) -> str:
    """把主题归一化,让「CI #512」「ci #512」「CI  512」认成同一个。"""
    text = re.sub(r"\s+", " ", (topic or "").strip().lower())
    return re.sub(r"[#:：]", "", text)


class FindingBoard:
    """发现板。无状态,所有方法都显式传 db —— 便于测试与并发。"""

    # ------------------------------------------------------------------ 互斥锁

    async def claim(self, topic: str) -> bool:
        """认领一个调查主题。拿不到 = 已经有别的 Agent 在查,本 Agent 应当跳过。

        这是**省钱的锁**:同一个 CI 被三个 Agent 各查一遍,模型调用就白烧三份。
        """
        key = f"finding:{normalize_topic(topic)}"
        got = await get_cache().acquire_lock(key, CLAIM_TTL_SECONDS)
        if not got:
            logger.info("主题「%s」已被其他 Agent 认领,跳过重复调查", topic)
        return got

    async def release(self, topic: str) -> None:
        await get_cache().release_lock(f"finding:{normalize_topic(topic)}")

    # ------------------------------------------------------------------ 变更集

    def publish(
        self,
        db: Session,
        *,
        run_id: int,
        repo_id: int,
        author: str,
        topic: str,
        conclusion: str,
        evidence: list[Any] | None = None,
        confidence: float = 0.5,
        status: str = m.FindingStatus.CONFIRMED.value,
        references: list[int] | None = None,
        supersedes_id: int | None = None,
        task_id: str | None = None,
    ) -> m.AgentFinding:
        """发布一条发现。**只增不改** —— 要修正就追加一条并指向旧的。"""
        finding = m.AgentFinding(
            run_id=run_id, repo_id=repo_id, task_id=task_id,
            author=author, topic=(topic or "")[:200], conclusion=conclusion,
            evidence=list(evidence or []), confidence=float(confidence),
            status=status, references=list(references or []),
            supersedes_id=supersedes_id,
        )
        db.add(finding)
        db.commit()
        db.refresh(finding)
        return finding

    def superseded_ids(self, db: Session, run_id: int) -> set[int]:
        """哪些发现已经被后来的发现推翻了。

        **注意这是算出来的,不是存在行上的**。发现不可改,所以不能在旧那条上
        写一个 `superseded` 状态;改成「有没有别的发现指向它」来推导。
        这也正是版本控制的做法:你不改写旧提交,而是追加一个引用它的新提交。
        """
        rows = db.scalars(
            select(m.AgentFinding.supersedes_id).where(
                m.AgentFinding.run_id == run_id,
                m.AgentFinding.supersedes_id.is_not(None),
            )
        ).all()
        return {int(r) for r in rows if r is not None}

    def read(self, db: Session, run_id: int, *,
             exclude_superseded: bool = True) -> list[m.AgentFinding]:
        """读出这次运行的全部发现,按时间序。

        `exclude_superseded=True` 时过滤掉被推翻的 —— 但**不是删除**:
        推翻这件事本身也是协作历史的一部分,只是不该再拿来当依据。
        """
        rows = list(db.scalars(
            select(m.AgentFinding)
            .where(m.AgentFinding.run_id == run_id)
            .order_by(m.AgentFinding.id.asc())
        ).all())
        if not exclude_superseded:
            return rows
        dead = self.superseded_ids(db, run_id)
        return [f for f in rows if f.id not in dead]

    def latest_by_topic(self, db: Session, run_id: int) -> dict[str, m.AgentFinding]:
        """每个主题取最新一条。用于判断「这个主题上有分歧吗」。"""
        latest: dict[str, m.AgentFinding] = {}
        for finding in self.read(db, run_id, exclude_superseded=False):
            latest[normalize_topic(finding.topic)] = finding
        return latest

    def conflicting_topics(self, db: Session, run_id: int) -> list[dict[str, Any]]:
        """同一主题上有**多条未被推翻的发现** —— 那就是分歧点。

        不判断谁对谁错:那是 observer 的活。这里只负责把分歧**标出来**,
        而不是像原先那样让它们混在一段文本里被和稀泥。
        """
        groups: dict[str, list[m.AgentFinding]] = {}
        for finding in self.read(db, run_id):
            groups.setdefault(normalize_topic(finding.topic), []).append(finding)

        return [
            {
                "topic": items[0].topic,
                "authors": [f.author for f in items],
                "conclusions": [f.conclusion for f in items],
                "finding_ids": [f.id for f in items],
            }
            for items in groups.values()
            if len({f.conclusion for f in items}) > 1
        ]


board = FindingBoard()