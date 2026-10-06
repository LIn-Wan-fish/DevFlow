from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rag.pipeline import search_with_trace
from app.rag.retriever import hybrid_search
from app.schemas.workspace import RagQueryRequest, RecallTestRequest

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/query")
def query(req: RagQueryRequest, db: Session = Depends(get_db)) -> dict:
    evidence = hybrid_search(db, req.repo_id, req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "evidence": [
            {"chunk_id": ev.chunk_id, "doc_path": ev.doc_path, "heading_path": ev.heading_path,
             "score": round(ev.score, 6), "citation": ev.citation,
             "preview": ev.content[:200]}
            for ev in evidence
        ],
    }


@router.post("/recall-test")
def recall_test(req: RecallTestRequest, db: Session = Depends(get_db)) -> dict:
    """四阶段中间结果:切分 / 向量召回 / 关键词召回 / RRF 融合 + 重排。

    用于诊断「检索不到到底是切分坏了、排序坏了,还是过滤把正确结果滤掉了」。
    """
    trace = search_with_trace(db, req.repo_id, req.query, top_k=req.top_k)
    return trace.as_dict()