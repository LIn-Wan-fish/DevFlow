"""Task 14 / 15 验收:SSE 对话、轨迹落库、Workspace REST、写操作闸门。"""

import json


# 角色走请求头,不再放请求体 —— 与前端、与后端 auth 依赖保持一致
_H_MEMBER = {"X-DevFlow-Role": "member"}
_H_VIEWER = {"X-DevFlow-Role": "viewer"}


def _sse(client, payload: dict):
    """发一次对话流请求。

    payload 里若带 "role",在这里转成请求头 —— 服务端**只认头**,不认请求体。
    """
    payload = dict(payload)
    role = payload.pop("role", "member")
    events: list[tuple[str, dict]] = []
    with client.stream("POST", "/api/chat/stream", json=payload,
                       headers={"X-DevFlow-Role": role}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("event: "):
                events.append((line[len("event: "):], {}))
            elif line.startswith("data: ") and events:
                try:
                    events[-1] = (events[-1][0], json.loads(line[len("data: "):]))
                except json.JSONDecodeError:
                    pass
    return events


def test_健康检查(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "mock"


def test_仓库列表(client):
    repos = client.get("/api/repos").json()
    assert repos and repos[0]["full_name"] == "acme/clowder-ai"


def test_health_六项统计与快照一致(client):
    health = client.get("/api/repos/1/health").json()
    assert set(health) == {"repo", "open_issues", "prs_pending_review", "issues_resolved",
                           "issues_rejected", "failed_ci", "merged_prs"}
    assert health["open_issues"] >= 3
    assert health["failed_ci"] >= 1
    assert health["merged_prs"] >= 1


def test_未知仓库_404(client):
    assert client.get("/api/repos/999/health").status_code == 404


def test_issues_支持状态筛选与搜索(client):
    items = client.get("/api/repos/1/issues").json()["items"]
    assert len(items) >= 3
    opened = client.get("/api/repos/1/issues?state=open").json()["items"]
    assert all(i["state"] == "open" for i in opened)
    hit = client.get("/api/repos/1/issues?q=登录").json()["items"]
    assert any("登录" in i["title"] for i in hit)


def test_issues_返回分组计数(client):
    groups = client.get("/api/repos/1/issues").json()["groups"]
    for key in ("unarchived", "discussing", "pending_decision", "handled", "rejected", "closed"):
        assert key in groups


def test_prs_带高风险标记(client):
    items = client.get("/api/repos/1/prs").json()["items"]
    pr = [p for p in items if p["number"] == 12][0]
    assert pr["files"]
    assert any(f["is_high_risk"] and "auth" in f["path"] for f in pr["files"])


def test_ci_列表(client):
    items = client.get("/api/repos/1/ci").json()["items"]
    assert any(r["conclusion"] == "failure" for r in items)


def test_召回测试返回四阶段(client):
    body = client.post("/api/rag/recall-test",
                       json={"repo_id": 1, "query": "登录接口变更"}).json()
    for stage in ("chunks", "vector_hits", "keyword_hits", "fused_reranked"):
        assert stage in body, f"召回测试必须能看到 {stage} 阶段"


def test_rag_query_带引用(client):
    body = client.post("/api/rag/query",
                       json={"repo_id": 1, "query": "refresh_token", "top_k": 3}).json()
    assert body["evidence"]
    assert body["evidence"][0]["doc_path"]
    assert body["evidence"][0]["citation"]


def test_对话流事件齐全且顺序合理(client):
    events = _sse(client, {"session_id": "s1", "repo_id": 1,
                           "message": "CI #512 为什么失败?", "role": "member"})
    kinds = [k for k, _ in events]
    assert kinds[0] == "run_started"
    assert "context" in kinds
    assert "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-1] == "done"
    assert kinds.index("tool_call") < kinds.index("tool_result")


def test_综合问题出现_plan_与_task_事件(client):
    events = _sse(client, {"session_id": "s2", "repo_id": 1,
                           "message": "检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
                           "role": "member"})
    kinds = [k for k, _ in events]
    assert "plan" in kinds
    assert "observation" in kinds
    assert kinds.count("task_started") >= 2


def test_运行结束后轨迹可查且四级能串起来(client):
    events = _sse(client, {"session_id": "s3", "repo_id": 1,
                           "message": "检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
                           "role": "member"})
    done = [payload for kind, payload in events if kind == "done"][0]
    trace = client.get(f"/api/runs/{done['run_id']}").json()
    assert trace["agent_run"]["status"] == "succeeded"
    assert trace["agent_run"]["stop_reason"] == "completed"
    assert trace["tool_calls"], "工具调用必须落库,否则出问题无法追溯"
    assert trace["workflow_runs"], "多 Agent 工作流必须留下 WorkflowRun"
    assert trace["task_runs"], "任务级别的轨迹也要留下"


def test_空消息_422(client):
    assert client.post("/api/chat/stream",
                       json={"session_id": "s", "repo_id": 1, "message": ""}).status_code == 422


def test_写操作只出草稿不执行(client):
    events = _sse(client, {"session_id": "s4", "repo_id": 1,
                           "message": "给 Issue #3 写一条查询评论草稿", "role": "member"})
    kinds = [k for k, _ in events]
    assert "draft" in kinds

    drafts = client.get("/api/drafts?status=pending").json()
    assert drafts, "草稿必须落库等待人工确认"

    audit = client.get("/api/drafts/audit").json()
    assert not [a for a in audit if a["result"] == "executed"], "未确认前不得执行"


def test_确认草稿后才执行并留审计(client):
    events = _sse(client, {"session_id": "s5", "repo_id": 1,
                           "message": "给 Issue #3 写一条查询评论草稿", "role": "member"})
    draft_id = [p for k, p in events if k == "draft"][0]["draft_id"]

    confirmed = client.post(f"/api/drafts/{draft_id}/confirm", headers=_H_MEMBER)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "executed"

    audit = client.get("/api/drafts/audit").json()
    assert any(a["result"] == "executed" and a["draft_id"] == draft_id for a in audit)


def test_viewer_确认草稿被拒且留审计(client):
    events = _sse(client, {"session_id": "s6", "repo_id": 1,
                           "message": "给 Issue #3 写一条查询评论草稿", "role": "viewer"})
    draft_id = [p for k, p in events if k == "draft"][0]["draft_id"]

    denied = client.post(f"/api/drafts/{draft_id}/confirm", headers=_H_VIEWER)
    assert denied.status_code == 403

    audit = client.get("/api/drafts/audit").json()
    assert any(a["result"] == "denied" for a in audit), "403 也必须留痕"


def test_重复确认返回冲突(client):
    events = _sse(client, {"session_id": "s7", "repo_id": 1,
                           "message": "给 Issue #3 写一条查询评论草稿", "role": "member"})
    draft_id = [p for k, p in events if k == "draft"][0]["draft_id"]
    client.post(f"/api/drafts/{draft_id}/confirm", headers=_H_MEMBER)
    assert client.post(f"/api/drafts/{draft_id}/confirm", headers=_H_MEMBER).status_code == 409


def test_记忆候选需批准才生效(client, indexed_store):
    from app.core.memory import MemHub

    # client 依赖同一个 indexed_store 夹具实例,所以两者看到的是同一份数据
    MemHub().record_candidate(indexed_store, repo_id=1, session_id=1, run_id=1,
                              content="CI 需要先跑 migrate", confidence=0.8)
    body = client.get("/api/memory/candidates?repo_id=1").json()
    assert body["candidates"]
    assert body["entries"] == []

    candidate_id = body["candidates"][0]["id"]
    approved = client.post(f"/api/memory/candidates/{candidate_id}/approve",
                           json={"approved_by": "member"})
    assert approved.status_code == 200

    after = client.get("/api/memory/candidates?repo_id=1").json()
    assert after["entries"]


def test_mcp_工具列表(client):
    body = client.get("/api/mcp/tools").json()
    assert body["transport"] == "inprocess"
    assert body["tools"]


def test_评测接口十题全通过(client):
    body = client.post("/api/eval/run", json={"mode": "mock"}).json()
    assert body["total"] == 10, body
    assert body["passed"] == 10, [c["key"] for c in body["cases"] if not c["passed"]]
    assert body["metrics"]["ragas"] == "skipped (mock mode)"

    runs = client.get("/api/eval/runs").json()
    assert runs and runs[0]["passed"] == 10



def test_对话结束后沉淀记忆候选但不生效(client):
    """跑一次 CI 排障,应当沉淀出候选;但没批准前不得进入已生效区。"""
    _sse(client, {"session_id": "mem-a", "repo_id": 1,
                  "message": "CI #512 为什么失败?", "role": "member"})
    body = client.get("/api/memory/candidates?repo_id=1").json()
    assert body["candidates"], "运行结束后应当沉淀出记忆候选"
    assert body["entries"] == [], "未批准前不得进入已生效区"


def test_批准后能被新会话召回(client):
    """验收 9:会话 A 沉淀 → 人工批准 → 会话 B 能召回。"""
    _sse(client, {"session_id": "mem-b1", "repo_id": 1,
                  "message": "CI #512 为什么失败?", "role": "member"})
    candidates = client.get("/api/memory/candidates?repo_id=1").json()["candidates"]
    assert candidates

    approved = client.post(f"/api/memory/candidates/{candidates[0]['id']}/approve",
                           json={"approved_by": "member"})
    assert approved.status_code == 200

    events = _sse(client, {"session_id": "mem-b2", "repo_id": 1,
                           "message": "再讲讲 CI #512 的失败原因", "role": "member"})
    context = [payload for kind, payload in events if kind == "context"][0]
    assert context["memory_hits"] >= 1, "已批准的记忆应当在后续会话被召回"


def test_未批准的记忆不参与召回(client):
    """同一批候选里,没批准的那条不能被召回。"""
    _sse(client, {"session_id": "mem-c", "repo_id": 1,
                  "message": "CI #512 为什么失败?", "role": "member"})
    before = client.get("/api/memory/candidates?repo_id=1").json()
    assert before["candidates"] and before["entries"] == []

    events = _sse(client, {"session_id": "mem-c2", "repo_id": 1,
                           "message": "再讲讲 CI #512 的失败原因", "role": "member"})
    context = [payload for kind, payload in events if kind == "context"][0]
    assert context["memory_hits"] == 0, "未批准的记忆绝不能参与召回"


def test_技能列表(client):
    body = client.get("/api/skills").json()
    names = [skill["name"] for skill in body["skills"]]
    assert "repo_health_report" in names


def test_技能按声明顺序执行(client):
    response = client.post("/api/skills/repo_health_report/run",
                           json={"inputs": {"repo_id": 1}})
    assert response.status_code == 200
    body = response.json()
    assert body["steps_executed"] == 2
    assert [step["tool"] for step in body["steps"]] == ["repo_health", "weekly_report"]


def test_技能缺必填入参返回_422(client):
    response = client.post("/api/skills/repo_health_report/run", json={"inputs": {}})
    assert response.status_code == 422


def test_不存在的技能返回_404(client):
    assert client.post("/api/skills/nope/run", json={"inputs": {}}).status_code == 404

# --------------------------------------------------------------------------- 权限


def _sse_raw(client, payload: dict, headers: dict | None = None):
    """不经 _sse 的翻译,原样发请求 —— 用来验证「请求体里的 role 无效」。"""
    events: list[tuple[str, dict]] = []
    with client.stream("POST", "/api/chat/stream", json=payload, headers=headers or {}) as response:
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[len("event: "):].strip()
                events.append((kind, {}))
            elif line.startswith("data: ") and events:
                try:
                    events[-1] = (kind, json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events, response


def test_认证模式端点如实报告演示模式(client):
    body = client.get("/api/auth/mode").json()
    assert body["mode"] == "demo"
    assert body["enforced"] is False, "没配令牌就必须如实说没有认证"


def test_未知角色被拒(client):
    response = client.post("/api/chat/stream",
                           json={"session_id": "s", "repo_id": 1, "message": "x"},
                           headers={"X-DevFlow-Role": "hacker"})
    assert response.status_code == 400


def test_请求体里的_role_不参与授权(client):
    """回归:角色原先从请求体读,任何人写 role=maintainer 就能执行写操作。

    现在服务端只认请求头。这里在**请求体**里塞 role=maintainer 且不带请求头,
    应当按默认 viewer 处理 → 确认草稿被拒。
    """
    events, _ = _sse_raw(client, {"session_id": "auth-body", "repo_id": 1,
                                  "message": "给 Issue #3 写一条查询评论草稿",
                                  "role": "maintainer"})
    drafts = [payload for kind, payload in events if kind == "draft"]
    assert drafts, "写操作仍应产出草稿"

    draft_id = drafts[0]["draft_id"]
    assert client.post(f"/api/drafts/{draft_id}/confirm").status_code == 403, \
        "请求体里的 role 绝不能提权"


def test_查询参数里的_role_不参与授权(client):
    """原先 ?role=member 能直接提权,现在必须无效。"""
    events, _ = _sse_raw(client, {"session_id": "auth-query", "repo_id": 1,
                                  "message": "给 Issue #3 写一条查询评论草稿"})
    draft_id = [payload for kind, payload in events if kind == "draft"][0]["draft_id"]
    assert client.post(f"/api/drafts/{draft_id}/confirm?role=maintainer").status_code == 403


def test_令牌模式_无令牌返回_401(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "devflow_role_tokens", "member:tok-member")
    response = client.post("/api/chat/stream",
                           json={"session_id": "t1", "repo_id": 1, "message": "x"})
    assert response.status_code == 401
    assert client.get("/api/auth/mode").json()["enforced"] is True


def test_令牌模式_令牌决定角色(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "devflow_role_tokens", "member:tok-member,viewer:tok-viewer")

    # member 令牌 → 可以确认草稿
    events, _ = _sse_raw(client, {"session_id": "t2", "repo_id": 1,
                                  "message": "给 Issue #3 写一条查询评论草稿"},
                         headers={"Authorization": "Bearer tok-member"})
    draft_id = [payload for kind, payload in events if kind == "draft"][0]["draft_id"]
    confirmed = client.post(f"/api/drafts/{draft_id}/confirm",
                            headers={"Authorization": "Bearer tok-member"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "executed"

    # viewer 令牌 → 被拒
    events2, _ = _sse_raw(client, {"session_id": "t3", "repo_id": 1,
                                   "message": "给 Issue #3 写一条查询评论草稿"},
                          headers={"Authorization": "Bearer tok-viewer"})
    draft2 = [payload for kind, payload in events2 if kind == "draft"][0]["draft_id"]
    denied = client.post(f"/api/drafts/{draft_id}".replace(str(draft_id), str(draft2)) + "/confirm",
                         headers={"Authorization": "Bearer tok-viewer"})
    assert denied.status_code == 403


def test_令牌模式_错误令牌被拒(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "devflow_role_tokens", "member:tok-member")
    response = client.post("/api/chat/stream",
                           json={"session_id": "t4", "repo_id": 1, "message": "x"},
                           headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401

def test_写操作执行失败返回_502_并留痕(client, db_with_snapshot, repo_id, monkeypatch):
    """回归:上游写入失败(GitHub 403 等)原先直接抛成没有任何信息的 500,

    调用方只知道「服务器错误」,不知道是令牌缺权限还是目标不存在。
    正确行为是:草稿标 failed、审计留一条 failed、HTTP 返回 502 并带上原因。
    """
    from app.db import models as m
    from app.safety import drafts as draft_store

    draft = m.ActionDraft(repo_id=repo_id, action="comment_on_issue", target="issue#3",
                          payload={"body": "演示"}, preview="将在 issue#3 下发表评论",
                          risk_level="low", status="pending")
    db_with_snapshot.add(draft)
    db_with_snapshot.commit()

    def boom(db, d):  # noqa: ANN001
        raise RuntimeError("发表评论失败:403 Resource not accessible by personal access token")

    monkeypatch.setattr(draft_store, "_execute", boom)

    response = client.post(f"/api/drafts/{draft.id}/confirm",
                           headers={"X-DevFlow-Role": "member"})

    assert response.status_code == 502, "上游失败应当是 502,不是 500"
    assert "403" in response.json()["detail"]

    db_with_snapshot.refresh(draft)
    assert draft.status == "failed", "失败的草稿不能留在 confirmed/executed"

    audit = client.get("/api/drafts/audit").json()
    assert any(a["draft_id"] == draft.id and a["result"] == "failed" for a in audit), \
        "写入失败必须留 failed 审计"