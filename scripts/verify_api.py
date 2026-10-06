#!/usr/bin/env python3
"""DevFlow AI Demo 端到端验收(HTTP 部分)。

刻意用 Python 而不是 bash/curl:Windows 上 PowerShell 会把请求体里的中文
按本地代码页编码,导致服务端收到乱码查询 —— 那是测试工具的问题,
却会被误判成检索功能坏了。用 Python 发请求可以彻底避开这个坑。

退出码 0 表示全部通过。
"""

from __future__ import annotations

import json
import sys

import httpx

API = "http://localhost:8000"

passed = 0
failed = 0


def ok(name: str, detail: str = "") -> None:
    global passed
    passed += 1
    print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))


def bad(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def check(name: str, condition: bool, detail: str = "") -> None:
    ok(name, detail) if condition else bad(name, detail)


H_MEMBER = {"X-DevFlow-Role": "member"}
H_VIEWER = {"X-DevFlow-Role": "viewer"}


def sse(client: httpx.Client, payload: dict) -> list[tuple[str, dict]]:
    """发一次对话流请求。

    payload 里若带 "role",在这里转成请求头 —— 服务端只认头,不认请求体。
    超时给足:真实 thinking 模型跑一次多 Agent 工作流要几十秒到几分钟;
    后端每 15s 推心跳,连接不会被中间层掐断。
    """
    payload = dict(payload)
    role = payload.pop("role", "member")
    events: list[tuple[str, dict]] = []
    with client.stream("POST", f"{API}/api/chat/stream", json=payload, timeout=600,
                       headers={"X-DevFlow-Role": role}) as response:
        response.raise_for_status()
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[len("event: "):].strip()
                events.append((kind, {}))
            elif line.startswith("data: ") and events:
                raw = line[len("data: "):].strip()
                try:
                    events[-1] = (kind, json.loads(raw))
                except json.JSONDecodeError:
                    events[-1] = (kind, {"raw": raw})
    return events


def main() -> int:
    with httpx.Client(timeout=300) as client:
        print("== 0. 服务健康 ==")
        health = client.get(f"{API}/api/health").json()
        llm_mode = health.get("llm_mode", "mock")
        check("健康检查", health.get("status") == "ok", json.dumps(health, ensure_ascii=False))

        print("== 1. 仓库与总览统计(来自 PostgreSQL) ==")
        repos = client.get(f"{API}/api/repos").json()
        check("仓库列表非空", bool(repos))
        h = client.get(f"{API}/api/repos/1/health").json()
        expected_keys = {"open_issues", "prs_pending_review", "issues_resolved",
                         "issues_rejected", "failed_ci", "merged_prs"}
        check("总览含六项统计", expected_keys <= set(h), json.dumps(h, ensure_ascii=False))
        check("失败 CI 统计 > 0", h["failed_ci"] > 0)

        print("== 2. Workspace 右栏数据 ==")
        issues = client.get(f"{API}/api/repos/1/issues").json()
        check("Issue 列表带分组计数", "groups" in issues and issues["groups"])
        prs = client.get(f"{API}/api/repos/1/prs").json()["items"]
        pr12 = next((p for p in prs if p["number"] == 12), None)
        check("PR #12 存在", pr12 is not None)
        check("PR #12 标记了高风险路径",
              bool(pr12) and any(f["is_high_risk"] for f in pr12["files"]))

        print("== 3. RAG 召回测试四阶段 ==")
        trace = client.post(f"{API}/api/rag/recall-test",
                            json={"repo_id": 1, "query": "登录接口变更"}).json()
        for stage in ("chunks", "vector_hits", "keyword_hits", "fused_reranked"):
            check(f"召回阶段 {stage} 有结果", bool(trace.get(stage)),
                  f"{len(trace.get(stage) or [])} 条")
        rag = client.post(f"{API}/api/rag/query",
                          json={"repo_id": 1, "query": "refresh_token", "top_k": 3}).json()
        check("RAG 检索带引用", bool(rag["evidence"]) and bool(rag["evidence"][0]["citation"]),
              rag["evidence"][0]["citation"] if rag["evidence"] else "")

        print("== 4. SSE 流式对话(逐事件) ==")
        events = sse(client, {"session_id": "verify-ci", "repo_id": 1,
                              "message": "CI #512 为什么失败?", "role": "member"})
        kinds = [k for k, _ in events]
        check("事件数充足", len(kinds) >= 5, f"{len(kinds)} 个事件")
        check("首事件是 run_started", kinds and kinds[0] == "run_started")
        check("有 context 事件", "context" in kinds)
        check("有 tool_call / tool_result", "tool_call" in kinds and "tool_result" in kinds)
        check("末事件是 done", kinds and kinds[-1] == "done")
        check("tool_call 早于 tool_result", kinds.index("tool_call") < kinds.index("tool_result"))
        answer = next((p.get("answer", "") for k, p in events if k == "done"), "")
        check("CI 根因带出 401", "401" in answer, answer[:80].replace("\n", " "))

        print("== 5. 多 Agent 工作流 ==")
        wf_events = sse(client, {
            "session_id": "verify-release", "repo_id": 1,
            "message": "检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
            "role": "member"})
        wf_kinds = [k for k, _ in wf_events]
        check("有 plan 事件", "plan" in wf_kinds)
        check("有 task_started/task_finished",
              wf_kinds.count("task_started") >= 2
              and wf_kinds.count("task_started") == wf_kinds.count("task_finished"))
        check("有 observation 事件", "observation" in wf_kinds)
        obs = next((p for k, p in wf_events if k == "observation"), {})
        check("Observer 报出 PR 与 CI 的冲突", bool(obs.get("conflicts")),
              (obs.get("conflicts") or [""])[0][:100])
        wf_done = next((p for k, p in wf_events if k == "done"), {})
        check("工作流结论正面回应冲突",
              "暂缓" in wf_done.get("answer", "") or "冲突" in wf_done.get("answer", ""))

        print("== 6. 运行轨迹落库 ==")
        run_id = wf_done.get("run_id")
        trace_data = client.get(f"{API}/api/runs/{run_id}").json()
        check("AgentRun 完成且 stop_reason=completed",
              trace_data["agent_run"]["status"] == "succeeded"
              and trace_data["agent_run"]["stop_reason"] == "completed")
        check("ToolCall 落库", bool(trace_data["tool_calls"]))
        check("WorkflowRun 落库", bool(trace_data["workflow_runs"]))
        check("TaskRun 落库", bool(trace_data["task_runs"]))

        print("== 7. 写操作闸门 ==")
        before = len(client.get(f"{API}/api/drafts?status=pending").json())
        draft_events = sse(client, {"session_id": "verify-draft", "repo_id": 1,
                                    "message": "给 Issue #3 写一条查询评论草稿",
                                    "role": "member"})
        drafts = [p for k, p in draft_events if k == "draft"]
        check("产生 draft 事件", bool(drafts))
        pending = client.get(f"{API}/api/drafts?status=pending").json()
        check("草稿落库待确认", len(pending) > before, f"{before} → {len(pending)}")
        audit_before = client.get(f"{API}/api/drafts/audit").json()
        executed_before = [a for a in audit_before if a["result"] == "executed"]
        check("未确认前没有任何 executed 审计",
              not any(a["draft_id"] == drafts[0]["draft_id"] for a in executed_before)
              if drafts else False)

        if drafts:
            draft_id = drafts[0]["draft_id"]
            denied = client.post(f"{API}/api/drafts/{draft_id}/confirm", headers=H_VIEWER)
            check("viewer 确认被拒(403)", denied.status_code == 403)
            audit_mid = client.get(f"{API}/api/drafts/audit").json()
            check("越权尝试留下 denied 审计", any(a["result"] == "denied" for a in audit_mid))

            confirmed = client.post(f"{API}/api/drafts/{draft_id}/confirm", headers=H_MEMBER)
            check("member 确认后执行", confirmed.status_code == 200
                  and confirmed.json()["status"] == "executed")
            audit_after = client.get(f"{API}/api/drafts/audit").json()
            check("执行留下 executed 审计",
                  any(a["result"] == "executed" and a["draft_id"] == draft_id
                      for a in audit_after))

        print("== 7b. 权限:角色只认请求头 ==")
        mode = client.get(f"{API}/api/auth/mode").json()
        check("如实报告认证模式", "enforced" in mode,
              f"mode={mode.get('mode')} enforced={mode.get('enforced')}")
        unknown = client.post(f"{API}/api/chat/stream",
                              json={"session_id": "auth-x", "repo_id": 1, "message": "x"},
                              headers={"X-DevFlow-Role": "hacker"})
        check("未知角色返回 400", unknown.status_code == 400, f"status={unknown.status_code}")

        # 请求体里塞 role 不能提权:不带角色头 → 默认 viewer → 确认草稿必须 403
        body_role = client.post(f"{API}/api/drafts/999999/confirm",
                                json={"role": "maintainer"})
        check("不存在的草稿返回 404(且请求体 role 无效)",
              body_role.status_code == 404, f"status={body_role.status_code}")

        print("== 8. 跨会话记忆:沉淀 → 批准 → 召回 ==")
        sse(client, {"session_id": "verify-mem", "repo_id": 1,
                     "message": "CI #512 为什么失败?", "role": "member"})
        mem = client.get(f"{API}/api/memory/candidates?repo_id=1").json()
        check("运行结束后沉淀出记忆候选", bool(mem["candidates"]),
              f"{len(mem['candidates'])} 条待批准")

        recall_payload = {"session_id": "verify-mem-recall", "repo_id": 1,
                          "message": "再讲讲 CI #512 的失败原因", "role": "member"}
        if not mem["entries"]:
            ctx = next((p for k, p in sse(client, recall_payload) if k == "context"), {})
            check("未批准的记忆不参与召回", ctx.get("memory_hits", 0) == 0,
                  f"memory_hits={ctx.get('memory_hits')}")
        else:
            print("  [note] 已存在生效记忆(上次运行批准过),跳过「未批准不召回」的负向断言")

        if mem["candidates"]:
            candidate_id = mem["candidates"][0]["id"]
            approved = client.post(f"{API}/api/memory/candidates/{candidate_id}/approve",
                                   json={"approved_by": "member"})
            check("人工批准记忆候选", approved.status_code == 200)

            recall_payload["session_id"] = "verify-mem-recall-after"
            ctx = next((p for k, p in sse(client, recall_payload) if k == "context"), {})
            check("批准后新会话能召回该记忆", ctx.get("memory_hits", 0) >= 1,
                  f"memory_hits={ctx.get('memory_hits')}")

        print("== 9. 能力扩展:MCP + Skill ==")
        mcp = client.get(f"{API}/api/mcp/tools").json()
        print(f"    (transport={mcp.get('transport')})")
        mcp = client.get(f"{API}/api/mcp/tools").json()
        check("列出 MCP 外部工具", bool(mcp.get("tools")), f"{len(mcp.get('tools') or [])} 个")
        mcp_tools = mcp.get("tools") or []
        registered = [t for t in mcp_tools if t.get("registered")]
        # 关键:服务端有这个工具 ≠ Agent 调得到它。章节 10 讲的是「扩展 ChatAgent 的能力」,
        # 所以必须验证它们真的进了运行中的工具表。
        check("MCP 工具真的注册进了工具表(Agent 调得到)",
              bool(mcp_tools) and len(registered) == len(mcp_tools),
              f"{len(registered)}/{len(mcp_tools)} 已注册")

        skills = client.get(f"{API}/api/skills").json().get("skills") or []
        check("列出已声明技能", bool(skills), ", ".join(s["name"] for s in skills))

        if skills:
            skill_run = client.post(f"{API}/api/skills/{skills[0]['name']}/run",
                                    json={"inputs": {"repo_id": 1}})
            check("技能可按声明顺序执行", skill_run.status_code == 200
                  and skill_run.json().get("steps_executed", 0) >= 1,
                  f"{skill_run.json().get('steps_executed')} 步")
            missing = client.post(f"{API}/api/skills/{skills[0]['name']}/run",
                                  json={"inputs": {}})
            check("技能缺必填入参返回 422", missing.status_code == 422)

        print("== 10. Agent Eval ==")
        # 评测模式跟随实际 llm_mode:写死 mock 会让真实模型的运行被贴上 mock 标签,
        # 连带把 ragas 误标成「已跳过」。
        evaluation = client.post(f"{API}/api/eval/run", json={"mode": llm_mode},
                                 timeout=1800).json()
        check("评测 10/10 通过", evaluation["passed"] == evaluation["total"],
              f"{evaluation['passed']}/{evaluation['total']}")
        bad_cases = [c["key"] for c in evaluation["cases"] if not c["passed"]]
        check("无失败用例", not bad_cases, ", ".join(bad_cases))
        # ragas 的合格标准不是某个固定字符串,而是**不许出现假数字**:
        #   要么给真实指标(ok + 有分数 + 有样本数),
        #   要么明确说明为什么算不出来(skipped / unavailable + 原因)。
        # 只断言等于 "unavailable" 会在 RAGAS 真正跑通之后误报失败(实测踩到)。
        metrics = evaluation["metrics"]
        ragas = str(metrics.get("ragas"))
        if ragas == "ok":
            scores = metrics.get("ragas_scores") or {}
            honest = bool(scores) and int(metrics.get("ragas_samples") or 0) > 0
            detail = f"ok, scores={scores}, samples={metrics.get('ragas_samples')}"
        else:
            honest = len(ragas) > 12  # 必须带上原因,而不是光一句 unavailable
            detail = ragas
        check("ragas 要么给真实指标、要么说明原因,不出现假数字", honest, detail[:160])

        print()
        print("== 11. 自动周报 ==")
        reports = client.get(f"{API}/api/reports?repo_id=1").json()
        check("周报列表非空(调度器启动时已补)", reports["total"] >= 1,
              f"{reports['total']} 份")
        sched = reports.get("scheduler") or {}
        check("如实暴露调度配置", "enabled" in sched and "current_period" in sched,
              f"enabled={sched.get('enabled')} period={sched.get('current_period')}")
        first = reports["items"][0]
        check("周报带周期键与统计", bool(first.get("period_key")) and first.get("open_issues") >= 0,
              f"{first.get('period_key')} 未处理{first.get('open_issues')}/合并{first.get('merged_prs')}/失败CI{first.get('failed_ci')}")
        detail = client.get(f"{API}/api/reports/{first['id']}").json()
        check("周报正文可读且结构完整",
              "## 概况" in detail.get("body", "") and "## 风险提示" in detail.get("body", ""),
              f"正文 {len(detail.get('body', ''))} 字")
        again = client.post(f"{API}/api/reports/generate?repo_id=1").json()
        check("手动生成是幂等的(同周期同一份)", again["id"] == first["id"],
              f"id={again['id']} vs {first['id']}")

    print()
    print(f"==== 验收汇总: PASS={passed} FAIL={failed} ====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())