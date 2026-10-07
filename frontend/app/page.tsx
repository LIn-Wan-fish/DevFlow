"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import ChatPanel from "@/components/ChatPanel";
import OverviewBar from "@/components/OverviewBar";
import ProjectSidebar, { type SessionNode } from "@/components/ProjectSidebar";
import AddProjectDialog from "@/components/AddProjectDialog";
import ResizeHandle from "@/components/ResizeHandle";
import ThemeToggle from "@/components/ThemeToggle";
import { usePanelWidth } from "@/lib/usePanelWidth";
import WorkspacePanel from "@/components/WorkspacePanel";
import { api } from "@/lib/api";
import type { CiItem, Health, IssueGroupCounts, IssueItem, MemoryCandidate,
  MemoryEntry, PrItem, Repo } from "@/lib/types";

export default function WorkspacePage() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState(1);
  const [adding, setAdding] = useState(false);

  // 左右面板宽度。各自的夹取范围不同:左侧是项目列表,太窄会看不清仓库名;
  // 右侧是工作区(分组统计 + 列表),内容更宽。
  const left = usePanelWidth({ storageKey: "devflow-w-left", initial: 248,
                               min: 180, max: 420, side: "left" });
  const right = usePanelWidth({ storageKey: "devflow-w-right", initial: 372,
                                min: 280, max: 640, side: "right" });
  const [health, setHealth] = useState<Health | null>(null);
  const [issues, setIssues] = useState<IssueItem[]>([]);
  const [groups, setGroups] = useState<IssueGroupCounts>({});
  const [prs, setPrs] = useState<PrItem[]>([]);
  const [ci, setCi] = useState<CiItem[]>([]);
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([]);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  // 存的是**会话 id**,不是标题。原先存标题,而两个项目下都有「默认会话」,
  // 于是点一个会把另一个也点亮 —— 标题是给人看的,不该当身份用。
  const [sessionId, setSessionId] = useState(1);
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

  // 选中态用「仓库:会话」复合键 —— 会话 id 在各仓库下是从 1 开始的,光用 id 会串。
  const activeSession = `${repoId}:${sessionId}`;
  const sessionTitle = sessions.find((s) => s.id === sessionId)?.title ?? "默认会话";
  // 给后端的会话键**必须带仓库**:原先直接拿标题当键,两个项目的「默认会话」
  // 会落进同一段对话历史里 —— 这是比高亮错更严重的数据串用。
  const chatSessionKey = `repo${repoId}-session${sessionId}`;

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
        activeSession={activeSession}
        onSelectRepo={setRepoId}
        onSelectSession={setSessionId}
        onRefresh={() => void reload()}
        onAddProject={() => setAdding(true)}
        width={left.width}
        footer={<ThemeToggle />}
      />

      <ResizeHandle handlers={left.handlers} resizing={left.resizing} label="调整项目栏宽度" />

      {adding ? (
        <AddProjectDialog
          onClose={() => setAdding(false)}
          onAdded={() => void reload()}
        />
      ) : null}

      <main className="flex h-full min-w-0 flex-1 flex-col">
        {repos.length === 0 ? (
          <div className="border-b border-line bg-warn-soft px-5 py-3 text-[12px] leading-relaxed text-warn">
            当前没有任何仓库数据。
            {error ? ` (${error})` : ""}
            若 <code>DATA_SOURCE=github</code>,请配置 <code>GITHUB_TOKEN</code> 与{" "}
            <code>GITHUB_REPO</code> 后重启后端 —— 系统不会用快照数据顶替。
          </div>
        ) : health ? (
          <OverviewBar
            health={health}
            repo={repoName}
            session={sessionTitle}
            onRefresh={() => void reload()}
          />
        ) : (
          <div className="border-b border-line bg-panel px-5 py-3 text-[12px] text-muted">
            {error ? `加载失败:${error}` : "正在加载总览…"}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-5 py-2 text-[11px]">
          <span className="text-muted">当前角色</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
            className="rounded-lg border border-line bg-canvas px-2 py-1 text-[11px] outline-none transition-colors focus:border-accent/60"
          >
            <option value="member">member</option>
            <option value="viewer">viewer</option>
            <option value="maintainer">maintainer</option>
          </select>
          <span className={authMode && !authMode.enforced ? "text-warn" : "text-muted"}>
            {authMode && !authMode.enforced
              ? "⚠ 演示模式:未配置角色令牌,角色由前端选择,不构成认证(配置 DEVFLOW_ROLE_TOKENS 后启用令牌认证)"
              : "已启用角色令牌认证(viewer 无写权限)"}
          </span>
        </div>

        <ChatPanel
          repoId={repoId}
          sessionId={chatSessionKey}
          role={role}
          quoted={quoted}
          onQuotedConsumed={() => setQuoted("")}
          onRunFinished={() => void reload()}
        />
      </main>

      <ResizeHandle handlers={right.handlers} resizing={right.resizing} label="调整工作区宽度" />
      <WorkspacePanel
        width={right.width}
        repoId={repoId}
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