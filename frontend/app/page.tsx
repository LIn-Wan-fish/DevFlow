"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import ChatPanel from "@/components/ChatPanel";
import OverviewBar from "@/components/OverviewBar";
import ProjectSidebar, { type SessionNode } from "@/components/ProjectSidebar";
import WorkspacePanel from "@/components/WorkspacePanel";
import { api } from "@/lib/api";
import type { CiItem, Health, IssueGroupCounts, IssueItem, MemoryCandidate,
  MemoryEntry, PrItem, Repo } from "@/lib/types";

export default function WorkspacePage() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState(1);
  const [health, setHealth] = useState<Health | null>(null);
  const [issues, setIssues] = useState<IssueItem[]>([]);
  const [groups, setGroups] = useState<IssueGroupCounts>({});
  const [prs, setPrs] = useState<PrItem[]>([]);
  const [ci, setCi] = useState<CiItem[]>([]);
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([]);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [session, setSession] = useState("默认会话");
  const [quoted, setQuoted] = useState("");
  const [role, setRole] = useState("member");
  const [authMode, setAuthMode] = useState<{ enforced: boolean; mode: string } | null>(null);
  const [error, setError] = useState("");

  const sessions: SessionNode[] = useMemo(
    () => [
      { id: 1, title: "默认会话", age: "当前" },
      { id: 2, title: "第二个会话测试", age: "5 天" },
    ],
    [],
  );

  const reload = useCallback(async () => {
    try {
      const [repoList, healthData, issueData, prData, ciData, memory, mode] = await Promise.all([
        api.repos(),
        api.health(repoId),
        api.issues(repoId),
        api.prs(repoId),
        api.ci(repoId),
        api.memory(repoId),
        api.authMode(),
      ]);
      setAuthMode(mode);
      setRepos(repoList);
      setHealth(healthData);
      setIssues(issueData.items);
      setGroups(issueData.groups);
      setPrs(prData.items);
      setCi(ciData.items);
      setCandidates(memory.candidates);
      setEntries(memory.entries);
      setError("");
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, [repoId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const repoName = repos.find((repo) => repo.id === repoId)?.full_name ?? `repo#${repoId}`;

  const approveMemory = async (id: number) => {
    await api.approveMemory(id, role);
    await reload();
  };

  const rejectMemory = async (id: number) => {
    await api.rejectMemory(id);
    await reload();
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <ProjectSidebar
        repos={repos}
        activeRepoId={repoId}
        sessions={sessions}
        activeSession={session}
        onSelectRepo={setRepoId}
        onSelectSession={setSession}
        onRefresh={() => void reload()}
        onAddProject={() => window.alert("Demo 只内置 acme/clowder-ai 一个仓库快照")}
      />

      <main className="flex h-full min-w-0 flex-1 flex-col">
        {repos.length === 0 ? (
          <div className="border-b border-line bg-amber-50 px-4 py-3 text-[12px] text-amber-800">
            当前没有任何仓库数据。
            {error ? ` (${error})` : ""}
            若 <code>DATA_SOURCE=github</code>,请配置 <code>GITHUB_TOKEN</code> 与{" "}
            <code>GITHUB_REPO</code> 后重启后端 —— 系统不会用快照数据顶替。
          </div>
        ) : health ? (
          <OverviewBar
            health={health}
            repo={repoName}
            session={session}
            onRefresh={() => void reload()}
          />
        ) : (
          <div className="border-b border-line bg-panel px-4 py-3 text-[12px] text-muted">
            {error ? `加载失败:${error}` : "正在加载总览…"}
          </div>
        )}

        <div className="flex items-center gap-2 border-b border-line bg-panel px-4 py-1 text-[11px]">
          <span className="text-muted">当前角色</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
            className="rounded border border-line px-1 py-0.5"
          >
            <option value="member">member</option>
            <option value="viewer">viewer</option>
            <option value="maintainer">maintainer</option>
          </select>
          <span className={authMode && !authMode.enforced ? "text-amber-700" : "text-muted"}>
            {authMode && !authMode.enforced
              ? "⚠ 演示模式:未配置角色令牌,角色由前端选择,不构成认证(配置 DEVFLOW_ROLE_TOKENS 后启用令牌认证)"
              : "已启用角色令牌认证(viewer 无写权限)"}
          </span>
        </div>

        <ChatPanel
          repoId={repoId}
          sessionId={session}
          role={role}
          quoted={quoted}
          onQuotedConsumed={() => setQuoted("")}
          onRunFinished={() => void reload()}
        />
      </main>

      <WorkspacePanel
        issues={issues}
        groups={groups}
        prs={prs}
        ci={ci}
        candidates={candidates}
        entries={entries}
        onQuote={(text) => setQuoted(text)}
        onApproveMemory={approveMemory}
        onRejectMemory={rejectMemory}
      />
    </div>
  );
}