"use client";

import type { Health } from "@/lib/types";

const CARDS: { key: keyof Health; label: string; alert?: boolean }[] = [
  { key: "open_issues", label: "待处理 Issue" },
  { key: "prs_pending_review", label: "待 Review PR" },
  { key: "issues_resolved", label: "已处理 Issue" },
  { key: "issues_rejected", label: "已拒绝 Issue" },
  { key: "failed_ci", label: "失败 CI", alert: true },
  { key: "merged_prs", label: "已合并 PR" },
];

type Props = {
  health: Health;
  repo: string;
  session: string;
  onRefresh?: () => void;
};

/** 中栏顶部:仓库/会话 + 六个统计卡片(对应 img_01 的统计条)。 */
export function OverviewBar({ health, repo, session, onRefresh }: Props) {
  return (
    <div className="border-b border-line bg-panel">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-4 py-2.5 text-[12px]">
        <span className="text-[13px] font-semibold tracking-tight">总览</span>
        <span className="text-muted">当前代码仓</span>
        <span className="rounded-full bg-sunken px-2.5 py-0.5 text-[11px] text-ink">{repo}</span>
        <span className="text-muted">会话: {session}</span>
        <span className="ml-auto rounded-full bg-accent-soft px-2.5 py-0.5 text-[11px] font-medium text-accent">
          Production Workspace
        </span>
        <button
          type="button"
          className="rounded-lg px-2 py-0.5 text-muted transition-colors hover:bg-hover hover:text-ink"
        >
          管理项目
        </button>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-lg px-2 py-0.5 text-muted transition-colors hover:bg-hover hover:text-accent"
        >
          刷新
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2 px-4 pb-3 md:grid-cols-6">
        {CARDS.map((card) => {
          const value = health?.[card.key] ?? 0;
          const highlight = card.alert && Number(value) > 0;
          return (
            <div
              key={card.key}
              className={`rounded-xl border px-2.5 py-2 text-center transition-colors ${
                highlight
                  ? "border-danger/30 bg-danger-soft"
                  : "border-line bg-sunken hover:border-line/80"
              }`}
            >
              <div className="truncate text-[11px] text-muted">{card.label}</div>
              <div
                className={`text-[20px] font-semibold leading-tight tabular-nums ${
                  highlight ? "text-danger" : "text-ink"
                }`}
              >
                {value}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default OverviewBar;