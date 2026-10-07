"use client";

import { useState } from "react";

import type { Draft } from "@/lib/types";

type Props = {
  draft: Draft;
  onConfirm: (id: number) => void | Promise<void>;
  onReject: (id: number) => void | Promise<void>;
};

/**
 * 草稿确认卡片。
 *
 * 高风险动作默认禁用确认按钮,必须先勾选风险确认 ——
 * 「模型提出操作,系统负责检查执行条件」在 UI 上也要体现出来。
 */
export function DraftCard({ draft, onConfirm, onReject }: Props) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);

  const isHighRisk = draft.risk_level === "high";
  const decided = draft.status !== "pending";

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm(draft.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={`mt-3 rounded-xl border p-3 shadow-soft ${
        isHighRisk ? "border-danger/40 bg-danger-soft" : "border-line bg-sunken"
      }`}
      data-testid={`draft-${draft.id}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] text-accent">草稿</span>
        <span className="font-medium">{draft.action}</span>
        <span className="text-muted">→ {draft.target}</span>
        {isHighRisk ? (
          <span className="rounded-md bg-danger px-1.5 py-0.5 text-[10px] text-white">高风险</span>
        ) : null}
        <span className="ml-auto rounded-md bg-panel px-1.5 py-0.5 text-[10px] text-muted">
          状态:{draft.status}
        </span>
      </div>

      <div className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed">{draft.preview}</div>

      {!decided ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {isHighRisk ? (
            <label className="flex items-center gap-1 text-[11px] text-danger">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              我已确认风险
            </label>
          ) : null}
          <button
            type="button"
            disabled={busy || (isHighRisk && !acknowledged)}
            onClick={handleConfirm}
            className="rounded-lg bg-accent px-3 py-1 text-[11px] font-medium text-white shadow-soft transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            确认执行
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onReject(draft.id)}
            className="rounded-lg border border-line bg-panel px-3 py-1 text-[11px] transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-40"
          >
            拒绝
          </button>
          <span className="text-[10px] text-muted">确认前不会产生任何副作用</span>
        </div>
      ) : null}
    </div>
  );
}

export default DraftCard;