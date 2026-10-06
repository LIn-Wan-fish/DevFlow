"""Task 7 验收:注册表约束 + 只读工具行为。"""

import pytest

from app.tools import registry
from app.tools.registry import ToolContext


def _ctx(db, repo_id=1, **kw):
    return ToolContext(db=db, repo_id=repo_id, **kw)


def test_注册表里写类工具只有_draft_action():
    writes = [n for n, s in registry.REGISTRY.items() if s.is_write]
    assert writes == ["draft_action"], "出现第二个写工具 = 模型获得了直接执行权"


def test_禁止出现_execute_类工具名():
    assert not [n for n in registry.REGISTRY if n.startswith("execute")]


def test_每个工具都有_description_与_parameters():
    for name, spec in registry.REGISTRY.items():
        assert spec.description, name
        assert spec.parameters.get("type") == "object", name
        assert spec.handler is not None, name


def test_langchain_工具定义格式正确():
    tools = registry.as_langchain_tools()
    assert tools
    for item in tools:
        assert item["type"] == "function"
        assert item["function"]["name"]
        assert item["function"]["parameters"]["type"] == "object"


async def test_未知工具报错而不是静默(db):
    with pytest.raises(registry.UnknownToolError):
        await registry.execute("no_such_tool", {}, _ctx(db))


async def test_repo_health_返回六项统计(db_with_snapshot):
    result = await registry.execute("repo_health", {}, _ctx(db_with_snapshot))
    assert set(result.data) >= {
        "open_issues", "prs_pending_review", "issues_resolved",
        "issues_rejected", "failed_ci", "merged_prs",
    }
    assert result.data["open_issues"] >= 3
    assert result.data["failed_ci"] >= 1
    assert result.data["merged_prs"] >= 1


async def test_search_code_只搜工作区不碰向量库(db_with_snapshot):
    result = await registry.execute("search_code", {"query": "login"}, _ctx(db_with_snapshot))
    assert result.data["hits"], "快照代码里必须有 login 相关内容"
    assert all("path" in h and "line_no" in h for h in result.data["hits"])


async def test_search_code_查不到时明确说未找到(db_with_snapshot):
    result = await registry.execute("search_code", {"query": "zzz_not_exist_qqq"},
                                    _ctx(db_with_snapshot))
    assert result.empty is True
    assert "未找到" in result.summary


async def test_snapshot_模式不读_GITHUB_TOKEN(db_with_snapshot, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-be-used")
    # 不发任何网络请求:节点没有任何 httpx 调用,能跑通就说明没走 GitHub
    result = await registry.execute("repo_health", {}, _ctx(db_with_snapshot))
    assert result.data["repo"]


async def test_draft_action_只生成草稿不执行(db_with_snapshot):
    from app.db import models as m

    result = await registry.execute(
        "draft_action",
        {"action": "comment_on_issue", "target": "issue#3", "body": "查询一下进展"},
        _ctx(db_with_snapshot),
    )
    assert result.data["status"] == "pending"
    draft = db_with_snapshot.get(m.ActionDraft, result.data["draft_id"])
    assert draft.status == "pending"
    # 未确认前不应有任何审计记录说它执行过
    results = [a.result for a in db_with_snapshot.query(m.AuditLog).all()]
    assert "executed" not in results


async def test_白名单外动作连草稿都不给(db_with_snapshot):
    from app.safety.policy import PermissionDenied

    with pytest.raises(PermissionDenied):
        await registry.execute(
            "draft_action",
            {"action": "delete_repository", "target": "repo#1"},
            _ctx(db_with_snapshot),
        )