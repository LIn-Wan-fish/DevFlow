"""Task 12 验收(预算部分):压缩顺序是契约,不是实现细节。"""

from app.core.budget import COMPRESSION_ORDER, AssembledContext, EvidenceItem, allocate


def _ctx(system="s", history=None, tool_results=None, evidence=None):
    return AssembledContext(
        system=system,
        history=history if history is not None else [],
        tool_results=tool_results if tool_results is not None else [],
        evidence=evidence if evidence is not None else [],
    )


def test_system_段永不被裁剪():
    ctx = _ctx(system="S" * 40000, history=[{"role": "human", "content": "hi"}])
    out = allocate(ctx, total=10)
    assert out.system == ctx.system, "system 承载角色与约束,裁掉等于换了个人"


def test_预算充足时什么都不压():
    ctx = _ctx(history=[{"role": "human", "content": "hi"}], tool_results=["t"], evidence=[])
    out = allocate(ctx, total=8000)
    assert out.compressed == []


def test_超压时先压工具结果():
    ctx = _ctx(history=[{"role": "human", "content": "h" * 400}],
               tool_results=["t" * 4000],
               evidence=[EvidenceItem("e" * 100, 0.9)])
    out = allocate(ctx, total=300)
    assert out.compressed == ["tool_results"], "工具结果可重取,应当第一个被压"
    assert out.history == ctx.history


def test_压完工具结果还不够才截证据():
    ctx = _ctx(history=[{"role": "human", "content": "h" * 400}],
               tool_results=["t" * 4000],
               evidence=[EvidenceItem("e" * 4000, 0.9), EvidenceItem("f" * 4000, 0.1)])
    out = allocate(ctx, total=300)
    assert out.compressed[:2] == ["tool_results", "evidence"]
    assert out.history == ctx.history, "对话历史最后才动"


def test_证据按分数从低到高丢():
    # 两段等长证据各约 375 token,给 420 只容得下一个:
    # 应当丢掉低分那一个,而不是两个都丢
    ctx = _ctx(tool_results=[],
               evidence=[EvidenceItem("a" * 1500, 0.1), EvidenceItem("b" * 1500, 0.9)])
    out = allocate(ctx, total=420)
    assert [e.score for e in out.evidence] == [0.9], "应当保住高分证据"


def test_三样都压完还超才丢历史():
    ctx = _ctx(history=[{"role": "human", "content": "old" * 8000},
                        {"role": "human", "content": "最后一个问题"}],
               tool_results=["t" * 8000],
               evidence=[EvidenceItem("e" * 8000, 0.5)])
    out = allocate(ctx, total=100)
    assert out.compressed == list(COMPRESSION_ORDER)
    assert out.history[-1]["content"] == "最后一个问题"


def test_压缩顺序常量就是设计的顺序():
    assert COMPRESSION_ORDER == ("tool_results", "evidence", "history")


def test_预算内不丢最近一轮():
    ctx = _ctx(history=[{"role": "human", "content": "old" * 9999},
                        {"role": "human", "content": "最后一个问题"}])
    out = allocate(ctx, total=200)
    assert out.history[-1]["content"] == "最后一个问题"


def test_用量统计可读():
    ctx = _ctx(history=[{"role": "human", "content": "hi"}])
    out = allocate(ctx, total=8000)
    assert set(out.used_segments) == {"system", "summary", "history", "tool_results", "evidence"}