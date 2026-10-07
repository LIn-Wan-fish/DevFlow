"use client";

import type { PrItem } from "@/lib/types";

/** 右栏 PR 标签页。高风险路径直接标出来,不藏在详情里。 */
export function PrList({ items, onQuote }: { items: PrItem[]; onQuote?: (n: number) => void }) {
  return (
    <ul className="space-y-1.5">
      {items.map((pr) => {
        const risky = (pr.files || []).filter((file) => file.is_high_risk);
        return (
          <li
            key={pr.id}
            className="rounded-xl border border-line bg-panel p-2.5 shadow-soft transition-all hover:border-accent/40 hover:shadow-card"
          >
            <div className="flex items-start gap-1.5">
              <span className="shrink-0 text-[11px] tabular-nums text-muted">#{pr.number}</span>
              <span className="flex-1 text-[12px] font-medium leading-snug">{pr.title}</span>
              <span
                className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10px] ${
                  pr.merged
                    ? "bg-ok-soft text-ok"
                    : "bg-warn-soft text-warn"
                }`}
              >
                {pr.merged ? "已合并" : pr.state}
              </span>
            </div>
            <div className="mt-1.5 text-[11px] text-muted">
              {pr.head_ref} → {pr.base_ref} · {pr.files?.length ?? 0} 个文件改动
            </div>
            {risky.length ? (
              <ul className="mt-1.5 space-y-0.5">
                {risky.map((file) => (
                  <li
                    key={file.path}
                    className="truncate rounded-md bg-danger-soft px-1.5 py-0.5 text-[10px] text-danger"
                  >
                    ⚠ 高风险 {file.path}
                  </li>
                ))}
              </ul>
            ) : null}
            <button
              type="button"
              onClick={() => onQuote?.(pr.number)}
              className="mt-2 rounded-md px-1.5 py-0.5 text-[10px] text-accent transition-colors hover:bg-accent-soft"
            >
              引用到对话
            </button>
          </li>
        );
      })}
      {!items.length ? (
        <li className="rounded-xl border border-dashed border-line p-4 text-center text-[11px] text-muted">
          没有 PR
        </li>
      ) : null}
    </ul>
  );
}

export default PrList;