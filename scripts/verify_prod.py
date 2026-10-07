#!/usr/bin/env python3
"""生产协作测试:开启角色令牌认证后的全方位验证。

和 verify_api.py 的区别:那个测**演示模式**(角色由请求头自称),
这个测**令牌认证模式** —— 也是唯一能证明「越权会被拦下」的模式。

用法(容器内):
    PYTHONPATH=/app TOKEN_VIEWER=xx TOKEN_MEMBER=yy TOKEN_MAINTAINER=zz \
        python /tmp/verify_prod.py

退出码 0 表示全部通过。
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

API = os.environ.get("API_URL", "http://localhost:8000")
V = os.environ.get("TOKEN_VIEWER", "")
M = os.environ.get("TOKEN_MEMBER", "")
T = os.environ.get("TOKEN_MAINTAINER", "")

passed = failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}" + (f" -- {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" -- {detail}" if detail else ""))


def hdr(token: str) -> dict:
    return {"X-DevFlow-Role-Token": token} if token else {}


def sse(client: httpx.Client, token: str, message: str, session: str) -> list:
    """发一次流式对话,返回 (事件名, 数据) 列表。"""
    body = {"session_id": session, "repo_id": 1, "message": message, "role": "member"}
    out = []
    with client.stream("POST", f"{API}/api/chat/stream", json=body,
                       headers={**hdr(token), "Content-Type": "application/json"},
                       timeout=900) as response:
        if response.status_code != 200:
            return [("__status__", {"code": response.status_code})]
        kind = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:") and kind:
                try:
                    out.append((kind, json.loads(line[5:].strip())))
                except json.JSONDecodeError:
                    out.append((kind, {}))
    return out


def main() -> int:
    print("== 0. 认证模式 ==")
    with httpx.Client(timeout=120) as client:
        mode = client.get(f"{API}/api/auth/mode").json()
        check("已进入令牌认证模式", mode.get("enforced") is True,
              f"mode={mode.get('mode')} enforced={mode.get('enforced')}")
        check("如实报告可用角色",
              set(mode.get("roles") or []) >= {"viewer", "member", "maintainer"},
              str(mode.get("roles")))

        print("\n== 1. 伪造角色必须无效(这套机制存在的理由) ==")
        r = client.post(f"{API}/api/chat/stream",
                        json={"session_id": "spoof", "repo_id": 1,
                              "message": "给 Issue #3 写一条查询评论草稿", "role": "maintainer"},
                        headers={"X-DevFlow-Role": "maintainer"}, timeout=600)
        check("不带令牌 + 自称 maintainer -> 401", r.status_code == 401,
              f"status={r.status_code}")

        print("\n== 2. 无效令牌 ==")
        r = client.get(f"{API}/api/drafts", headers=hdr("dv_totally_wrong_token"))
        check("无效令牌 -> 401", r.status_code == 401, f"status={r.status_code}")

        print("\n== 3. 真令牌能读 ==")
        r = client.get(f"{API}/api/drafts", headers=hdr(V))
        check("viewer 令牌可读草稿列表", r.status_code == 200, f"status={r.status_code}")
        r = client.get(f"{API}/api/repos", headers=hdr(V))
        check("viewer 令牌可读仓库", r.status_code == 200 and len(r.json()) >= 1)

        print("\n== 4. 造一份草稿(member) ==")
        events = sse(client, M, "给 Issue #3 写一条查询评论草稿", "prod-draft")
        drafts = [d for k, d in events if k == "draft"]
        # 事件里的字段名是 draft_id,不是 id —— 我第一次写成了 id,导致误判"没造出草稿"
        draft_id = drafts[0].get("draft_id") if drafts else None
        check("member 一次对话就产生了待确认草稿", draft_id is not None,
              f"draft_id={draft_id}")

        if draft_id:
            print("\n== 5. 越权:viewer 确认必须被拒 ==")
            r = client.post(f"{API}/api/drafts/{draft_id}/confirm", headers=hdr(V))
            check("viewer 确认草稿 -> 403", r.status_code == 403, f"status={r.status_code}")

            print("\n== 6. 越权尝试要留审计 ==")
            audit = client.get(f"{API}/api/drafts/audit", headers=hdr(V)).json()
            denied = [a for a in audit if a.get("result") == "denied"]
            check("审计里有 denied 记录", len(denied) > 0, f"{len(denied)} 条")

            print("\n== 7. member 确认后真的执行 ==")
            r = client.post(f"{API}/api/drafts/{draft_id}/confirm", headers=hdr(M))
            check("member 确认草稿 -> 200", r.status_code == 200, f"status={r.status_code}")
            audit = client.get(f"{API}/api/drafts/audit", headers=hdr(V)).json()
            check("审计里出现 executed",
                  any(a.get("result") == "executed" for a in audit))

        print("\n== 8. 多 Agent 协作(member 令牌) ==")
        started = time.time()
        events = sse(client, M, "结合 PR #12 和 CI #512,判断这个版本能不能发布?", "prod-collab")
        kinds = {k for k, _ in events}
        check("触发了多 Agent 工作流", "plan" in kinds and "observation" in kinds,
              f"{len(events)} 个事件,用时 {time.time() - started:.0f}s")
        check("有 tool_call / tool_result 配对",
              "tool_call" in kinds and "tool_result" in kinds)

        run_ids = [d.get("run_id") for k, d in events if k == "run_started"]
        run_id = run_ids[0] if run_ids else None
        check("拿到 run_id", run_id is not None, str(run_id))

        if run_id:
            print("\n== 9. 共享发现板与协作图 ==")
            g = client.get(f"{API}/api/runs/{run_id}/findings", headers=hdr(M)).json()
            authors = g.get("authors") or []
            check("发现板上有多个 Agent 的发现", len(g.get("findings", [])) >= 3,
                  f"{len(g.get('findings', []))} 条,作者={authors}")
            check("存在引用关系(协作图有边)", len(g.get("edges", [])) > 0,
                  f"{len(g.get('edges', []))} 条边")
            check("综合节点汇聚了上游",
                  any(len(f.get("references") or []) >= 2 for f in g.get("findings", [])))

        print("\n== 10. 多副本经网关 ==")
        codes = [client.get(f"{API}/api/repos/1/health", headers=hdr(V)).status_code
                 for _ in range(12)]
        check("连续 12 次请求全部 200(经 nginx 分发)", all(c == 200 for c in codes),
              f"状态码集合={sorted(set(codes))}")

        print("\n== 11. 未认证的接口面 ==")
        check("健康检查免认证(探活用)", client.get(f"{API}/api/health").status_code == 200)
        r = client.get(f"{API}/api/repos", headers={})
        check("业务读接口需要令牌", r.status_code == 401, f"status={r.status_code}")

    print()
    print(f"==== 生产协作测试汇总: PASS={passed} FAIL={failed} ====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())