"use client";

import type { IssueGroupCounts, IssueItem } from "@/lib/types";

export const GROUP_LABELS: { key: string; label: string }[] = [
  { key: "unarchived", label: "未归档" },
  { key: "discussing", label: "讨论中" },
  { key: "pending_decision", label: "待决策" },
  { key: "handled", label: "已处理" },
  { key: "rejected", label: "已拒绝" },
  { key: "closed", label: "已关闭" },
];

type Props = {
  items: IssueItem[];
  groups: IssueGroupCounts;
  onQuote?: (issueNumber: number) => void;
};

/** 右栏 Issue 标签页(对应 img_01 右上区域)。 */
export function IssueList({ items, groups, onQuote }: Props) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-1">
        {GROUP_LABELS.map((group) => (
          <div key={group.key} className="rounded border border-line px-1.5 py-1 text-center">
            <div className="text-[10px] text-muted">{group.label}</div>
            <div className="text-[13px] font-semibold">{groups?.[group.key] ?? 0}</div>
          </div>
        ))}
      </div>

      <ul className="space-y-1">
        {items.map((issue) => (
          <li key={issue.id} className="rounded border border-line bg-panel p-2">
            <div className="flex items-start gap-1">
              <span className="text-[11px] font-medium text-muted">#{issue.number}</span>
              <span className="flex-1 text-[12px] font-medium leading-snug">{issue.title}</span>
              <span className="shrink-0 rounded bg-canvas px-1 text-[10px] text-muted">
                {issue.state}
              </span>
            </div>
            {issue.excerpt ? (
              <p className="mt-1 line-clamp-2 text-[11px] text-muted">{issue.excerpt}</p>
            ) : null}
            <div className="mt-1 flex flex-wrap items-center gap-1">
              {(issue.labels || []).slice(0, 3).map((label) => (
                <span key={label} className="rounded bg-canvas px-1 text-[10px] text-muted">
                  {label}
                </span>
              ))}
              <button
                type="button"
                onClick={() => onQuote?.(issue.number)}
                className="ml-auto text-[10px] text-accent hover:underline"
              >
                引用到对话
              </button>
            </div>
          </li>
        ))}
        {!items.length ? <li className="p-2 text-[11px] text-muted">没有匹配的 Issue</li> : null}
      </ul>
    </div>
  );
}

export default IssueList;