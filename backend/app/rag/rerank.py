"""重排。

这里是词法重排(词项覆盖 + 位置接近度),不是交叉编码器。
理由:Demo 要在离线模式下也确定可复现。生产环境把 rerank() 换成
rerank 模型即可,调用方签名不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")


def _terms(text: str) -> list[str]:
    """全部词项(含单字)。仅用于诊断与测试。"""
    lowered = (text or "").lower()
    terms = re.findall(r"[a-z0-9_]+", lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        terms.extend(run)
        terms.extend(run[i : i + 2] for i in range(len(run) - 1))
    return terms


def strong_terms(text: str) -> list[str]:
    """强词项:双字及以上的中文词、长度 >=2 的英文词。

    单个汉字太弱了 —— 一个「与」字就能让任意文档"命中"。
    """
    lowered = (text or "").lower()
    terms = [w for w in re.findall(r"[a-z0-9_]+", lowered) if len(w) >= 2]
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        terms.extend(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            terms.append(run)  # 单词查询(如「猫」)也要能命中
    return list(dict.fromkeys(terms))


# 只算「强词项」(双字及以上),单字不作为证据 —— 一个「与」字不该让任意文档"命中"。
#
# 两道门槛(实测标定,不是拍脑袋):
#
#  MIN_QUERY_PRESENCE:查询的强词项里,有多大比例**在语料中出现过**。
#    离题问题的词表与语料几乎不重叠。例如「量子纠缠模块 实现」的 6 个强词项里,
#    只有「实现」在语料中存在 → 1/6 = 0.17,判为离题,直接不返回证据。
#    这一条比「词项稀有度」更能区分噪声:refresh_token 在 21 个切分里出现 4 次,
#    按稀有度算并不"稀有",但它在语料中确实存在,是有效信号。
#
#  MIN_COVERAGE:在语料中存在的那些词项里,命中权重的占比。
#    防止只命中一个词就当成证据。
MIN_QUERY_PRESENCE = 0.30
# 查询里在语料中**真实出现过**的词项,至少要有这么多个。
# 比例的绝对下限:防止「把查询写短」把比例抬过门槛。
MIN_MATCHED_TERMS = 2
MIN_COVERAGE = 0.20
MAX_IDF = 4.0

# 引用门槛:**比检索门槛更严**。
#
# 理由:检索是「把候选给模型看」,引用是「标成用户可查的证据」—— 这两件事的公信力要求不同。
# 词袋匹配天生可以被「把问题拆成几个泛化词」绕过:实测离题查询
# 「量子 系统 设计」只碰到 1~2 个真实存在的词项,却因为命中的都是文中的稀有词,
# 覆盖率反而高达 1.00(比任何正常查询都高)。所以**覆盖率分不开**,
# 但「查询里到底有几个词真的在语料里出现过」可以:正常查询是 3~6,这种只有 2。
#
# 注意这**不**影响模型拿到候选,只影响最终挂出去的引用 —— 少给引用比给错引用代价小。
CITATION_MIN_TERMS = 3


@dataclass
class RankedItem:
    key: int
    score: float
    coverage: float = 0.0
    # 本次查询里在语料中真实出现过的词项数(查询级,对同一次检索的所有结果相同)
    present_terms: int = 0


def rerank(
    query: str,
    candidates: list[tuple[int, str]],
    top_k: int,
    *,
    idf: dict[str, float] | None = None,
) -> list[RankedItem]:
    """candidates: [(chunk_id, content)]。返回按相关度排序的前 top_k。

    idf 由调用方按整个仓库语料算出;不传则退化为等权(单测里常用)。
    """
    q_terms = strong_terms(query)
    if not q_terms:
        return [RankedItem(cid, 0.0) for cid, _ in candidates[:top_k]]

    basis = q_terms
    if idf is not None:
        # 语料词表 = idf 的键集合
        present = [term for term in q_terms if term in idf]
        if len(present) / len(q_terms) < MIN_QUERY_PRESENCE:
            # 查询词表与语料几乎不重叠 → 这是离题问题,不要硬凑证据
            return []
        # 绝对条数也要够。**比例可以被「把查询写短」绕过**:
        # 实测真实模型把「项目里量子纠缠模块怎么实现?」(12 个词项 / 2 个存在 / 比例 0.17)
        # 改写成「量子 模块 设计」(3 个词项 / 1 个存在 / 比例 0.33),就跨过了比例门槛,
        # 拿回 2 条与问题无关的文档并挂成引用 —— 答案明明写着「未找到」。
        # 无论怎么改写,**语料里真的出现过的词项始终只有 1 个**,那不足以构成证据。
        if len(q_terms) >= 3 and len(present) < MIN_MATCHED_TERMS:
            return []
        basis = present or q_terms

    def weight(term: str) -> float:
        if idf is None:
            return 1.0
        return idf.get(term, MAX_IDF)

    total = sum(weight(term) for term in basis) or 1.0

    scored: list[RankedItem] = []
    for chunk_id, content in candidates:
        c_terms = _terms(content)
        if not c_terms:
            continue
        unique = set(c_terms)
        matched = [term for term in basis if term in unique]
        if not matched:
            continue
        coverage = sum(weight(t) for t in matched) / total
        if coverage < MIN_COVERAGE:
            continue
        # 词频密度:命中次数 / 文本长度,避免长文本靠长度取胜
        density = sum(1 for t in c_terms if t in q_terms) / len(c_terms)
        scored.append(RankedItem(chunk_id, 0.7 * coverage + 0.3 * density * 10, coverage,
                                 present_terms=len(basis)))

    scored.sort(key=lambda item: (-item.score, item.key))
    return scored[:top_k]