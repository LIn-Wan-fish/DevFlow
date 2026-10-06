"use client";

import { useState } from "react";

import { api } from "@/lib/api";

/**
 * 添加项目。
 *
 * 刻意**不做乐观更新**:后端要先确认仓库真的可见、再同步数据,
 * 成功之后前端才刷新列表。失败时把服务端的原话显示出来 ——
 * 「没配令牌」「仓库不存在」「连不上 GitHub」是三件不同的事,
 * 糊成一句"添加失败"会让人无从下手。
 */
export default function AddProjectDialog({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const submit = async () => {
    const value = name.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    try {
      const repo = await api.addRepo(value);
      setDone(`已添加 ${repo.full_name},数据同步完成。`);
      onAdded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
         onClick={onClose}>
      <div className="w-[520px] rounded-lg border border-line bg-panel p-4 shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1 text-[14px] font-semibold">添加项目</h2>
        <p className="mb-3 text-[12px] text-muted">
          填 GitHub 仓库的 owner/name,也可以直接粘贴仓库地址。
          添加后会把该仓库的 Issue / PR / CI 同步到本地库(与内置快照仓库并列,互不影响)。
        </p>

        <div className="flex gap-2">
          <input
            autoFocus
            className="min-w-0 flex-1 rounded border border-line bg-canvas px-2 py-1.5 text-[12px] outline-none focus:border-ink"
            placeholder="例如 LIn-Wan-fish/DevFlow"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          />
          <button
            className="rounded bg-ink px-3 py-1.5 text-[12px] text-white disabled:opacity-40"
            disabled={busy || !name.trim()}
            onClick={() => void submit()}
          >
            {busy ? "同步中…" : "添加"}
          </button>
        </div>

        {busy ? (
          <p className="mt-2 text-[11px] text-muted">
            正在确认仓库并同步数据,首次可能要几十秒…
          </p>
        ) : null}
        {error ? (
          <p className="mt-2 rounded bg-red-50 px-2 py-1.5 text-[11px] text-red-600">{error}</p>
        ) : null}
        {done ? (
          <p className="mt-2 rounded bg-emerald-50 px-2 py-1.5 text-[11px] text-emerald-700">{done}</p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded border border-line px-3 py-1 text-[12px]" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
