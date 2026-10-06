from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.eval.harness import history, run_eval

router = APIRouter(prefix="/api/eval", tags=["Agent 评测"])

DATASET = "tests/data/eval_cases.json"


class EvalRequest(BaseModel):
    mode: str | None = None
    dataset: str = DATASET
    repo_id: int = 1


@router.post("/run", summary="跑一轮评测(10 个用例 + RAGAS 判分)")
async def run(req: EvalRequest, db: Session = Depends(get_db)) -> dict:
    try:
        result = await run_eval(db, req.dataset, mode=req.mode or settings.llm_mode,
                                repo_id=req.repo_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"评测集不存在:{exc}") from exc
    return result.as_dict()


@router.get("/runs", summary="历史评测结果")
def list_runs(db: Session = Depends(get_db)) -> list[dict]:
    return history(db)