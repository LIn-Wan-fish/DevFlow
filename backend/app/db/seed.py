"""把内置研发数据快照装载进库。

幂等:重复调用不产生重复行(按自然键判存在)。
快照刻意做成**自洽**的一条故事线:
  PR #12 改的是登录 → CI #512 挂的也是登录 → Issue #24 报的还是登录。
不这样设计,多 Agent 的冲突检测(PR 说可合、CI 说阻塞)就没有意义。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as m
from app.safety.policy import is_high_risk_path


def _resolve_snapshot_dir() -> Path:
    """容器内用 SNAPSHOT_DIR;在宿主跑单测时回退到仓库内的 data/snapshot。"""
    configured = Path(settings.snapshot_dir)
    if configured.exists():
        return configured
    return Path(__file__).resolve().parents[2] / "data" / "snapshot"


SNAPSHOT_DIR = _resolve_snapshot_dir()


def _read(name: str) -> list[dict]:
    path = SNAPSHOT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"快照文件缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _upsert_repo(db: Session, raw: dict) -> m.Repo:
    repo = db.scalar(select(m.Repo).where(m.Repo.owner == raw["owner"], m.Repo.name == raw["name"]))
    if repo is None:
        repo = m.Repo(**raw)
        db.add(repo)
        db.flush()
    return repo


def load_snapshot(db: Session) -> dict[str, int]:
    counts = {"repos": 0, "issues": 0, "pull_requests": 0, "ci_runs": 0, "documents": 0}

    repos = [_upsert_repo(db, raw) for raw in _read("repos.json")]
    repo = repos[0]
    counts["repos"] = len(repos)

    for raw in _read("issues.json"):
        exists = db.scalar(
            select(m.Issue).where(m.Issue.repo_id == repo.id, m.Issue.number == raw["number"])
        )
        if exists:
            continue
        db.add(m.Issue(repo_id=repo.id, **raw))
        counts["issues"] += 1

    for raw in _read("pull_requests.json"):
        exists = db.scalar(
            select(m.PullRequest).where(
                m.PullRequest.repo_id == repo.id, m.PullRequest.number == raw["number"]
            )
        )
        if exists:
            continue
        files = raw.pop("files", [])
        pr = m.PullRequest(repo_id=repo.id, **raw)
        db.add(pr)
        db.flush()
        for f in files:
            # 高风险判定走 policy,不在这里手写路径规则
            pr.files.append(
                m.PrFile(
                    path=f["path"],
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                    patch_summary=f.get("patch_summary", ""),
                    is_high_risk=is_high_risk_path(f["path"]),
                )
            )
        counts["pull_requests"] += 1

    for raw in _read("ci_runs.json"):
        exists = db.scalar(
            select(m.CiRun).where(m.CiRun.repo_id == repo.id, m.CiRun.number == raw["number"])
        )
        if exists:
            continue
        log_file = raw.pop("log_file", "")
        log_path = str(SNAPSHOT_DIR / log_file) if log_file else ""
        db.add(m.CiRun(repo_id=repo.id, log_path=log_path, **raw))
        counts["ci_runs"] += 1

    docs_dir = SNAPSHOT_DIR / "docs"
    for path in sorted(docs_dir.glob("*.md")):
        rel = f"docs/{path.name}"
        exists = db.scalar(
            select(m.Document).where(m.Document.repo_id == repo.id, m.Document.path == rel)
        )
        if exists:
            continue
        text = path.read_text(encoding="utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), path.stem)
        db.add(m.Document(repo_id=repo.id, path=rel, title=title, doc_type="markdown", version="v1.2"))
        counts["documents"] += 1

    db.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="装载内置研发数据快照")
    parser.add_argument("--repo", type=int, default=None, help="保留参数,快照是全量装载")
    parser.parse_args()

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        counts = load_snapshot(db)
    print(f"快照装载完成: {counts}  (来源 {SNAPSHOT_DIR})")


if __name__ == "__main__":
    main()