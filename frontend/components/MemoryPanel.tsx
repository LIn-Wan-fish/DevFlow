"use client";

import type { MemoryCandidate, MemoryEntry } from "@/lib/types";

type Props = {
  candidates: MemoryCandidate[];
  entries: MemoryEntry[];
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
};

/**
 * 记忆与知识库。
 *
 * 「候选」与「已生效」刻意分成两个区:未批准的候选不会参与召回,
 * 界面上也必须看得出这条经验还没生效。
 */
export function MemoryPanel({ candidates, entries, onApprove, onReject }: Props) {
  return (
    <div className="space-y-3">
      <section>
        <h4 className="mb-1 text-[11px] font-semibold text-muted">
          待批准候选({candidates.length})
        </h4>
        <ul className="space-y-1">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="rounded border border-line bg-panel p-2">
              <p className="text-[12px] leading-snug">{candidate.content}</p>
              <div className="mt-1 flex items-center gap-2 text-[10px] text-muted">
                <span>置信度 {candidate.confidence.toFixed(2)}</span>
                <span>来源运行 #{candidate.run_id ?? "-"}</span>
                <button
                  type="button"
                  onClick={() => onApprove?.(candidate.id)}
                  className="ml-auto rounded bg-accent px-1.5 py-0.5 text-white"
                >
                  批准
                </button>
                <button
                  type="button"
                  onClick={() => onReject?.(candidate.id)}
                  className="rounded border border-line px-1.5 py-0.5"
                >
                  忽略
                </button>
              </div>
            </li>
          ))}
          {!candidates.length ? (
            <li className="text-[11px] text-muted">没有待批准的记忆候选</li>
          ) : null}
        </ul>
      </section>

      {entries.length ? (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold text-muted">已生效({entries.length})</h4>
          <ul className="space-y-1">
            {entries.map((entry) => (
              <li key={entry.id} className="rounded border border-line bg-canvas p-2">
                <p className="text-[12px] leading-snug">{entry.content}</p>
                <div className="mt-1 text-[10px] text-muted">
                  由 {entry.approved_by} 批准 · 已进入召回范围
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export default MemoryPanel;