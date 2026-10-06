"""切分 → Embedding → 写 chunks 表 + Milvus。

幂等:重建前先按 repo_id 清理两处,避免旧切分残留导致检索命中过期内容。
代码永不入库 —— 这条规则由这里只扫 documents 表来保证。
"""

from __future__ import annotations

import argparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.embeddings import embed_texts
from app.db import models as m
from app.rag.splitter import split_document
from app.rag.vectorstore import get_vector_store


def index_repo(db: Session, repo_id: int) -> dict[str, int]:
    store = get_vector_store()
    store.ensure_collection()
    store.delete_repo(repo_id)
    db.execute(delete(m.Chunk).where(m.Chunk.repo_id == repo_id))
    db.commit()

    documents = db.scalars(select(m.Document).where(m.Document.repo_id == repo_id)).all()
    total_chunks = 0
    for document in documents:
        text = _document_text(document)
        chunks = split_document(document.path, text)
        if not chunks:
            continue
        vectors = embed_texts([c.content for c in chunks])
        rows = [
            m.Chunk(
                document_id=document.id,
                repo_id=repo_id,
                chunk_index=chunk.chunk_index,
                heading_path=chunk.heading_path,
                content=chunk.content,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ]
        db.add_all(rows)
        db.flush()
        for row in rows:
            row.milvus_id = row.id
        store.upsert([r.id for r in rows], [repo_id] * len(rows), vectors)
        total_chunks += len(rows)
    db.commit()
    return {"documents": len(documents), "chunks": total_chunks}


def _document_text(document: m.Document) -> str:
    """文档正文来源:快照模式下直接读文件,避免把正文冗余存两份。"""
    from app.db.seed import SNAPSHOT_DIR

    path = SNAPSHOT_DIR / document.path
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="为仓库建立 RAG 索引")
    parser.add_argument("--repo", type=int, required=True)
    args = parser.parse_args()

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        stats = index_repo(db, args.repo)
    print(f"索引完成 repo={args.repo}: {stats}")


if __name__ == "__main__":
    main()