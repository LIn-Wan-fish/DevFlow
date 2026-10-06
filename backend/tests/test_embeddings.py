"""Task 6 验收:确定性、归一化、有区分度。"""

import math

from app.core.embeddings import EMBED_DIM, cosine, embed_query, embed_texts


def test_维度一致():
    assert len(embed_query("x")) == EMBED_DIM
    assert all(len(v) == EMBED_DIM for v in embed_texts(["a", "b"]))


def test_确定性():
    assert embed_query("登录接口") == embed_query("登录接口")


def test_已归一化():
    assert math.isclose(sum(x * x for x in embed_query("abc")), 1.0, rel_tol=1e-6)


def test_不同文本向量不同():
    assert embed_query("登录接口") != embed_query("部署流程")


def test_共享词越多越相似():
    base = embed_query("登录 接口 变更 说明")
    near = embed_query("登录 接口 变更 历史")
    far = embed_query("部署 流水线 缓存 配置")
    assert cosine(base, near) > cosine(base, far)


def test_空文本不炸():
    assert len(embed_query("")) == EMBED_DIM