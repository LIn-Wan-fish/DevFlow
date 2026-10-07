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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40"
         onClick={onClose}>
      <div className="w-[520px] rounded-2xl border border-line bg-panel p-5 shadow-pop"
           onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1.5 text-[15px] font-semibold tracking-tight">添加项目</h2>
        <p className="mb-4 text-[12px] leading-relaxed text-muted">
          填 GitHub 仓库的 owner/name,也可以直接粘贴仓库地址。
          添加后会把该仓库的 Issue / PR / CI 同步到本地库(与内置快照仓库并列,互不影响)。
        </p>

        <div className="flex gap-2">
          <input
            autoFocus
            className="min-w-0 flex-1 rounded-lg border border-line bg-canvas px-3 py-2 text-[12px] outline-none transition-colors placeholder:text-muted/70 focus:border-accent/60"
            placeholder="例如 LIn-Wan-fish/DevFlow"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          />
          <button
            className="shrink-0 rounded-lg bg-accent px-4 py-2 text-[12px] font-medium text-white shadow-soft transition-opacity hover:opacity-90 disabled:opacity-40"
            disabled={busy || !name.trim()}
            onClick={() => void submit()}
          >
            {busy ? "同步中…" : "添加"}
          </button>
        </div>

        {busy ? (
          <p className="mt-2.5 text-[11px] text-muted">
            正在确认仓库并同步数据,首次可能要几十秒…
          </p>
        ) : null}
        {error ? (
          <p className="mt-2.5 rounded-lg border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-[11px] text-danger">
            {error}
          </p>
        ) : null}
        {done ? (
          <p className="mt-2.5 rounded-lg border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[11px] text-ok">
            {done}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            className="rounded-lg border border-line px-3 py-1.5 text-[12px] transition-colors hover:border-accent/50 hover:text-accent"
            onClick={onClose}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
