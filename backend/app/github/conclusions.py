"""CI 结论的语义。

**只把 `"failure"` 当失败是错的。** GitHub 的 `conclusion` 还有
`startup_failure` / `timed_out` / `cancelled` / `action_required`,
它们同样是「这次流水线没能正常跑完」。

真实数据里踩到的:用户仓库 6 次运行**全是 `startup_failure`**,
而总览统计、失败 CI 选取、周报、Observer 的冲突判定都写的是
`conclusion == "failure"` —— 于是系统得出「没有失败 CI」,
Observer 甚至据此说出「所有 CI 均通过」。这是同一处判断错在 5 个地方各写了一遍。
"""

from __future__ import annotations

# 只有这几种算「正常结束且无需关注」
HEALTHY_CONCLUSIONS: frozenset[str] = frozenset({"success", "skipped", "neutral"})


def is_failed_conclusion(conclusion: str | None) -> bool:
    """这次运行是否需要当成失败来对待。

    注意是「不在正常集合里」,而不是「等于 failure」——
    名单式判断会在 GitHub 新增结论时静默漏掉。
    """
    return (conclusion or "").strip().lower() not in HEALTHY_CONCLUSIONS


def healthy_filter(column):  # noqa: ANN001, ANN201
    """给 SQLAlchemy 列生成「非正常结束」的过滤条件。"""
    return column.notin_(tuple(HEALTHY_CONCLUSIONS))