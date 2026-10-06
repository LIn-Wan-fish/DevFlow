"use client";

import type { CiItem } from "@/lib/types";

/** 右栏 CI 标签页。失败的直接高亮,便于一眼定位要排障的那次。 */
export function CiList({ items, onQuote }: { items: CiItem[]; onQuote?: (n: number) => void }) {
  return (
    <ul className="space-y-1">
      {items.map((run) => (
        <li key={run.id} className="rounded border border-line bg-panel p-2">
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted">#{run.number}</span>
            <span className="flex-1 text-[12px] font-medium">{run.workflow}</span>
            <span
              className={`rounded px-1 text-[10px] ${
                run.conclusion === "failure"
                  ? "bg-danger-soft text-danger"
                  : "bg-ok-soft text-ok"
              }`}
            >
              {run.conclusion}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-muted">
            {run.branch} · {run.duration_seconds}s
          </div>
          {run.conclusion === "failure" ? (
            <button
              type="button"
              onClick={() => onQuote?.(run.number)}
              className="mt-1 text-[10px] text-accent hover:underline"
            >
              引用到对话
            </button>
          ) : null}
        </li>
      ))}
      {!items.length ? <li className="p-2 text-[11px] text-muted">没有 CI 记录</li> : null}
    </ul>
  );
}

export default CiList;