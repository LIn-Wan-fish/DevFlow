"""Task 8 验收:切分、融合、仓库隔离、空结果不臆造。"""

import pytest
from sqlalchemy import select

from app.db import models as m
from app.rag.indexer import index_repo
from app.rag.retriever import hybrid_search, keyword_search, rrf_fuse, vector_search
from app.rag.splitter import split_document
from app.rag.vectorstore import InMemoryVectorStore, set_vector_store


@pytest.fixture
def indexed(db_with_snapshot):
    set_vector_store(InMemoryVectorStore())
    repo_id = db_with_snapshot.query(m.Repo).one().id
    index_repo(db_with_snapshot, repo_id)
    yield db_with_snapshot
    set_vector_store(None)


# --------------------------------------------------------------------- 切分


def test_按标题层级切分并带_heading_path():
    md = "# 登录接口\n\n简介。\n\n## v1.2 变更\n\n新增 refresh_token。\n\n## 错误码\n\n401 未授权。\n"
    chunks = split_document("docs/api.md", md)
    paths = [c.heading_path for c in chunks]
    assert any("登录接口" in p for p in paths)
    assert any("v1.2 变更" in p for p in paths)
    assert any("refresh_token" in c.content for c in chunks)
    # 标题层级要串成路径,不是只有一个末级标题
    assert any(p.startswith("登录接口 > ") for p in paths)


def test_超长小节被二次切分():
    md = "# A\n\n" + "\n\n".join("句子。" * 60 for _ in range(12))
    chunks = split_document("docs/big.md", md)
    assert len(chunks) > 1
    assert all(c.token_count > 0 for c in chunks)


def test_代码按函数边界切分():
    code = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    chunks = split_document("src/x.py", code)
    assert len(chunks) >= 2
    assert any("def a" in c.content for c in chunks)


# --------------------------------------------------------------------- 融合


def test_rrf_融合把两边都靠前的排在前面():
    fused = rrf_fuse(["a", "b", "c"], ["b", "a", "d"], k=60)
    order = [key for key, _ in fused]
    assert set(order[:2]) == {"a", "b"}
    assert order[-1] in {"c", "d"}


def test_rrf_分数随名次单调下降():
    fused = dict(rrf_fuse(["a", "b", "c"]))
    assert fused["a"] > fused["b"] > fused["c"]


# --------------------------------------------------------------------- 检索


def test_索引后有切分与向量(indexed):
    repo_id = 1
    assert indexed.scalar(select(m.Chunk.id).where(m.Chunk.repo_id == repo_id)) is not None
    assert vector_search(repo_id, "登录接口", limit=5)


def test_关键词召回命中标识符(indexed):
    ids = keyword_search(indexed, repo_id=1, query="refresh_token")
    assert ids, "精确标识符必须能被关键词通道召回"


def test_检索强制仓库隔离(indexed):
    """跨仓库的内容绝不能进入证据集。"""
    other = m.Repo(owner="other", name="other-repo")
    indexed.add(other)
    indexed.flush()
    doc = m.Document(repo_id=other.id, path="docs/api.md", title="别的仓库", doc_type="markdown")
    indexed.add(doc)
    indexed.flush()
    indexed.add(m.Chunk(document_id=doc.id, repo_id=other.id, content="登录接口 refresh_token 别的仓库的内容"))
    indexed.commit()

    evidence = hybrid_search(indexed, repo_id=1, query="登录接口", top_k=6)
    assert evidence
    assert all(ev.repo_id == 1 for ev in evidence)


def test_检索结果带引用信息(indexed):
    evidence = hybrid_search(indexed, repo_id=1, query="refresh_token", top_k=3)
    assert evidence
    assert evidence[0].doc_path
    assert evidence[0].heading_path is not None
    assert evidence[0].citation


def test_查不到就返回空而不是编造(indexed):
    assert hybrid_search(indexed, repo_id=1, query="量子纠缠与猫咪毛色遗传", top_k=3) == []

# --------------------------------------------------------------------------- 离题门槛


@pytest.mark.parametrize("query", [
    "项目里量子纠缠模块怎么实现?",
    "量子纠缠模块 实现",
    "量子 模块 设计",
    "这个项目的量子计算调度器在哪",
])
def test_离题查询不返回任何证据(indexed, query):
    """没有证据就必须返回空 —— 不允许用低相关文档兜底。

    返回了就会挂成引用,用户看到的是「答案说未找到,下面却列着引用」。
    """
    assert hybrid_search(indexed, repo_id=1, query=query, top_k=5) == []


def test_缩短查询不能绕过离题门槛(indexed):
    """回归:真实模型会把长查询**改短**来绕过比例门槛。

    实测:把「项目里量子纠缠模块怎么实现?」(12 个词项 / 2 个存在 / 比例 0.17)
    改写成「量子 模块 设计」(3 个词项 / 1 个存在 / 比例 0.33),跨过了 0.30 的门槛,
    于是拿回 2 条与问题无关的文档并挂成引用 —— 而答案明明写着「未找到」。

    无论怎么改写,**语料中真实出现过的词项始终只有 1 个**,所以绝对条数才是稳定判据。
    """
    assert hybrid_search(indexed, repo_id=1, query="量子 模块 设计", top_k=5) == []


def test_正常查询不受新的绝对门槛影响(indexed):
    """加绝对门槛不能误伤正常查询。"""
    for query in ("CI #512 为什么失败?", "登录接口是怎么实现的",
                  "PR #12 的改动有没有风险", "refresh_token 怎么刷新"):
        hits = hybrid_search(indexed, repo_id=1, query=query, top_k=5)
        assert hits, f"正常查询不该被误判为离题:{query}"

# --------------------------------------------------------------------------- 引用门槛


@pytest.mark.parametrize("query", [
    "量子 系统 设计",
    "量子纠缠 系统 设计",
])
def test_离题查询的弱命中不挂成引用(indexed, query):
    """回归:答案是「未找到」,下面却列着引用。

    根因:词袋匹配可以被「把问题拆成几个泛化词」绕过 —— 实测「量子 系统 设计」
    只碰到 2 个真实存在的词项,但命中的都是文中稀有词,覆盖率反而 **1.00**
    (比任何正常查询都高,因为分母剔除了缺失词项)。所以覆盖率分不开,
    能分开的是「查询里到底有几个词真在语料里出现过」:正常查询是 3~6,这种只有 2。

    处理方式:**候选照常给模型看,但不作为依据呈现给用户** ——
    少给引用比给错引用代价小。
    """
    hits = hybrid_search(indexed, repo_id=1, query=query, top_k=5)
    assert hits, "弱命中仍然要返回给模型(它需要上下文判断)"
    assert not any(h.strong for h in hits), "但不该挂成引用"


@pytest.mark.parametrize("query", [
    "CI #512 为什么失败?",
    "登录接口是怎么实现的",
    "token 过期后 refresh_token 怎么刷新",
    "PR #12 的改动有没有风险",
])
def test_正常查询的证据仍然可引用(indexed, query):
    """加了引用门槛不能把正常证据也拦掉。"""
    hits = hybrid_search(indexed, repo_id=1, query=query, top_k=5)
    assert hits
    assert all(h.strong for h in hits), f"正常证据必须可引用:{query}"