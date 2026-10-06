"""测试夹具。

原则:单测永不联网、永不依赖容器。
- 关系库用 SQLite in-memory(模型刻意只用可移植类型)
- Milvus 用内存假实现
- LLM 走 DeterministicChatModel(见 tests/test_llm.py)
"""

from __future__ import annotations

import os

# 必须在 import app.* 之前把环境变量摆好:app.config 在模块级构造 settings。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://devflow:devflow@postgres:5432/devflow")
os.environ.setdefault("MILVUS_URI", "http://milvus:19530")
os.environ.setdefault("SNAPSHOT_DIR", "/app/data/snapshot")

# 这三个开关必须**强制**覆盖,不能用 setdefault。
# 原因:.env 切到 LLM_MODE=openai 之后,容器环境里就带着 openai,
# setdefault 不会覆盖它 —— 单测会真的去打真实模型,既慢又不确定,
# 「单测永不联网」这条不变量就名存实亡了。
os.environ["LLM_MODE"] = "mock"
os.environ["EMBED_MODE"] = "mock"
os.environ["DATA_SOURCE"] = "snapshot"
# MCP 测试一律走进程内 transport:不拉起子进程,单测才稳定、才不依赖外部环境。
# 真实 stdio 由 tests/test_mcp.py 里显式构造 MCPClient(transport="stdio") 覆盖。
os.environ["MCP_TRANSPORT"] = "inprocess"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db import models as m  # noqa: E402
from app.db.seed import load_snapshot  # noqa: E402


@pytest.fixture
def db() -> Session:
    """裸库:只建表,不装快照。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def db_with_snapshot(db: Session) -> Session:
    """装了内置研发数据快照的库。"""
    load_snapshot(db)
    return db


@pytest.fixture
def repo_id(db_with_snapshot: Session) -> int:
    return db_with_snapshot.query(m.Repo).filter_by(name="clowder-ai").one().id


@pytest.fixture
def indexed_store(db_with_snapshot: Session) -> Session:
    """用进程内向量库建好索引。测试不依赖 Milvus。"""
    from app.rag.indexer import index_repo
    from app.rag.vectorstore import InMemoryVectorStore, set_vector_store

    set_vector_store(InMemoryVectorStore())
    repo = db_with_snapshot.query(m.Repo).filter_by(name="clowder-ai").one()
    index_repo(db_with_snapshot, repo.id)
    yield db_with_snapshot
    set_vector_store(None)


@pytest.fixture
def client(indexed_store: Session):
    """API 测试客户端。

    刻意不用 with 语句:那会触发 lifespan,而 lifespan 会去连真实的
    PostgreSQL 与 Milvus。测试只跑 SQLite + 进程内向量库。
    """
    from fastapi.testclient import TestClient

    from app.api.chat import get_tracer
    from app.db.session import get_db
    from app.main import app
    from app.observability.tracing import RunTracer

    app.dependency_overrides[get_db] = lambda: indexed_store
    app.dependency_overrides[get_tracer] = lambda: RunTracer(indexed_store)
    yield TestClient(app)
    app.dependency_overrides.clear()