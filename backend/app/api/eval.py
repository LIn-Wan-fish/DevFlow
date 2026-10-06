from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.eval.harness import history, run_eval

router = APIRouter(prefix="/api/eval", tags=["eval"])

DATASET = "tests/data/eval_cases.json"


class EvalRequest(BaseModel):
    mode: str | None = None
    dataset: str = DATASET
    repo_id: int = 1


@router.post("/run")
async def run(req: EvalRequest, db: Session = Depends(get_db)) -> dict:
    try:
        result = await run_eval(db, req.dataset, mode=req.mode or settings.llm_mode,
                                repo_id=req.repo_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"评测集不存在:{exc}") from exc
    return result.as_dict()


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict]:
    return history(db)