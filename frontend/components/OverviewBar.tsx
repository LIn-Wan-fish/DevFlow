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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-[12px]">
        <span className="font-semibold">总览</span>
        <span className="text-muted">当前代码仓</span>
        <span className="rounded bg-canvas px-2 py-0.5">{repo}</span>
        <span className="text-muted">会话: {session}</span>
        <span className="ml-auto rounded border border-accent px-2 py-0.5 text-[11px] text-accent">
          Production Workspace
        </span>
        <button type="button" className="text-muted hover:text-ink">
          管理项目
        </button>
        <button type="button" onClick={onRefresh} className="text-muted hover:text-ink">
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
              className="rounded border border-line bg-canvas px-2 py-1.5 text-center"
            >
              <div className="text-[11px] text-muted">{card.label}</div>
              <div
                className={`text-[18px] font-semibold leading-tight ${
                  highlight ? "text-red-500" : "text-ink"
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