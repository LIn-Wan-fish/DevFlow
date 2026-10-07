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
      <div className="grid grid-cols-3 gap-1.5">
        {GROUP_LABELS.map((group) => (
          <div
            key={group.key}
            className="rounded-lg border border-line bg-sunken px-1.5 py-1.5 text-center"
          >
            <div className="truncate text-[10px] text-muted">{group.label}</div>
            <div className="text-[14px] font-semibold tabular-nums">
              {groups?.[group.key] ?? 0}
            </div>
          </div>
        ))}
      </div>

      <ul className="space-y-1.5">
        {items.map((issue) => (
          <li
            key={issue.id}
            className="rounded-xl border border-line bg-panel p-2.5 shadow-soft transition-all hover:border-accent/40 hover:shadow-card"
          >
            <div className="flex items-start gap-1.5">
              <span className="shrink-0 text-[11px] font-medium tabular-nums text-muted">
                #{issue.number}
              </span>
              <span className="flex-1 text-[12px] font-medium leading-snug">{issue.title}</span>
              <span className="shrink-0 rounded-md bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
                {issue.state}
              </span>
            </div>
            {issue.excerpt ? (
              <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-muted">
                {issue.excerpt}
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {(issue.labels || []).slice(0, 3).map((label) => (
                <span
                  key={label}
                  className="rounded-md bg-sunken px-1.5 py-0.5 text-[10px] text-muted"
                >
                  {label}
                </span>
              ))}
              <button
                type="button"
                onClick={() => onQuote?.(issue.number)}
                className="ml-auto rounded-md px-1.5 py-0.5 text-[10px] text-accent transition-colors hover:bg-accent-soft"
              >
                引用到对话
              </button>
            </div>
          </li>
        ))}
        {!items.length ? (
          <li className="rounded-xl border border-dashed border-line p-4 text-center text-[11px] text-muted">
            没有匹配的 Issue
          </li>
        ) : null}
      </ul>
    </div>
  );
}

export default IssueList;