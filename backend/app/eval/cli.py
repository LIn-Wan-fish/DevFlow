"""命令行跑评测:python -m app.eval.cli --dataset tests/data/eval_cases.json"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.db import models as m  # noqa: F401  确保表注册
from app.eval.harness import run_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent Eval")
    parser.add_argument("--dataset", default="tests/data/eval_cases.json")
    parser.add_argument("--mode", default=None)
    parser.add_argument("--repo", type=int, default=1)
    args = parser.parse_args()

    from app.config import settings
    from app.db.base import Base
    from app.db.session import SessionLocal, engine

    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        result = asyncio.run(run_eval(db, args.dataset,
                                      mode=args.mode or settings.llm_mode, repo_id=args.repo))

    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    print(f"\n通过 {result.passed}/{result.total}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())