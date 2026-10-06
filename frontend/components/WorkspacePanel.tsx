"use client";

import { useState } from "react";

import ReportsPanel from "@/components/ReportsPanel";

import CiList from "./CiList";
import IssueList from "./IssueList";
import MemoryPanel from "./MemoryPanel";
import PrList from "./PrList";
import type { CiItem, IssueGroupCounts, IssueItem, MemoryCandidate, MemoryEntry, PrItem } from "@/lib/types";

const TABS = ["Issue", "PR", "CI", "周报", "团队", "记忆&知识库"] as const;
type Tab = (typeof TABS)[number];

type Props = {
  repoId: number;
  /** 由拖拽决定;不传则用默认宽度 */
  width?: number;
  issues: IssueItem[];
  groups: IssueGroupCounts;
  prs: PrItem[];
  ci: CiItem[];
  candidates: MemoryCandidate[];
  entries: MemoryEntry[];
  onQuote: (text: string) => void;
  onApproveMemory?: (id: number) => void;
  onRejectMemory?: (id: number) => void;
};

const TEAM = [
  { name: "wangwu", area: "auth", role: "maintainer" },
  { name: "lisi", area: "ui / infra", role: "member" },
  { name: "zhangsan", area: "api", role: "member" },
];

/** 右栏 Workspace(对应 img_01 右侧五个标签页)。 */
export function WorkspacePanel({
  repoId,
  width = 372,
  issues,
  groups,
  prs,
  ci,
  candidates,
  entries,
  onQuote,
  onApproveMemory,
  onRejectMemory,
}: Props) {
  const [tab, setTab] = useState<Tab>("Issue");
  const [keyword, setKeyword] = useState("");
  const [state, setState] = useState("");
  const [assignee, setAssignee] = useState("");

  const filtered = issues.filter((issue) => {
    if (keyword && !`${issue.title}${issue.excerpt}`.includes(keyword)) return false;
    if (state && issue.state !== state) return false;
    if (assignee && issue.assignee !== assignee) return false;
    return true;
  });

  return (
    <aside style={{ width }} className="flex h-full shrink-0 flex-col border-l border-line bg-canvas">
      <div className="flex items-center gap-1 border-b border-line bg-panel px-2 py-1.5">
        <span className="mr-auto text-[12px] font-semibold">Workspace</span>
        {TABS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setTab(item)}
            className={`rounded px-1.5 py-0.5 text-[11px] ${
              tab === item ? "bg-ink text-white" : "text-muted hover:bg-canvas"
            }`}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {tab === "Issue" ? (
          <>
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="关键词搜索标题、正文、标签"
              className="mb-2 w-full rounded border border-line px-2 py-1 text-[11px]"
            />
            <div className="mb-2 flex gap-1">
              <select
                value={state}
                onChange={(event) => setState(event.target.value)}
                className="flex-1 rounded border border-line px-1 py-0.5 text-[10px]"
              >
                <option value="">全部状态</option>
                <option value="open">open</option>
                <option value="closed">closed</option>
              </select>
              <select
                value={assignee}
                onChange={(event) => setAssignee(event.target.value)}
                className="flex-1 rounded border border-line px-1 py-0.5 text-[10px]"
              >
                <option value="">全部负责人</option>
                <option value="wangwu">wangwu</option>
                <option value="lisi">lisi</option>
                <option value="zhangsan">zhangsan</option>
              </select>
              <select
                className="flex-1 rounded border border-line px-1 py-0.5 text-[10px]"
                defaultValue="all"
              >
                <option value="all">全部时间</option>
              </select>
            </div>
            <IssueList items={filtered} groups={groups} onQuote={(n) => onQuote(`Issue #${n} `)} />
          </>
        ) : null}

        {tab === "PR" ? <PrList items={prs} onQuote={(n) => onQuote(`PR #${n} `)} /> : null}
        {tab === "CI" ? <CiList items={ci} onQuote={(n) => onQuote(`CI #${n} `)} /> : null}
        {tab === "周报" ? <ReportsPanel repoId={repoId} /> : null}

        {tab === "团队" ? (
          <ul className="space-y-1">
            {TEAM.map((member) => (
              <li key={member.name} className="rounded border border-line bg-panel p-2">
                <div className="text-[12px] font-medium">{member.name}</div>
                <div className="text-[10px] text-muted">
                  {member.area} · {member.role}
                </div>
              </li>
            ))}
          </ul>
        ) : null}

        {tab === "记忆&知识库" ? (
          <MemoryPanel
            candidates={candidates}
            entries={entries}
            onApprove={onApproveMemory}
            onReject={onRejectMemory}
          />
        ) : null}
      </div>
    </aside>
  );
}

export default WorkspacePanel;