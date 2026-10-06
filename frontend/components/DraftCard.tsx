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
      className={`mt-2 rounded border p-2 ${
        isHighRisk ? "border-red-300 bg-red-50" : "border-line bg-canvas"
      }`}
      data-testid={`draft-${draft.id}`}
    >
      <div className="flex items-center gap-2 text-[11px]">
        <span className="rounded bg-ink px-1.5 py-0.5 text-white">草稿</span>
        <span className="font-medium">{draft.action}</span>
        <span className="text-muted">→ {draft.target}</span>
        {isHighRisk ? (
          <span className="rounded bg-red-500 px-1.5 py-0.5 text-white">高风险</span>
        ) : null}
        <span className="ml-auto text-muted">状态:{draft.status}</span>
      </div>

      <div className="mt-1 whitespace-pre-wrap text-[12px]">{draft.preview}</div>

      {!decided ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {isHighRisk ? (
            <label className="flex items-center gap-1 text-[11px] text-red-600">
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
            className="rounded bg-accent px-2 py-1 text-[11px] text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            确认执行
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onReject(draft.id)}
            className="rounded border border-line px-2 py-1 text-[11px] hover:border-ink"
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