"""SQLAlchemy engine 与请求级会话。

注意:运行轨迹(observability/tracing.py)刻意使用独立会话,
不能复用请求会话 —— 流式响应期间事务边界会和 SSE 事件交错。
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()