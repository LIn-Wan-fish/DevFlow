"use client";

import { useState } from "react";

import RecallStages from "@/components/RecallStages";
import { api } from "@/lib/api";
import type { RecallTrace } from "@/lib/types";

export default function RagPage() {
  const [query, setQuery] = useState("登录接口变更");
  const [trace, setTrace] = useState<RecallTrace | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setTrace(await api.recallTest(1, query));
      setError("");
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1400px] p-8">
      <header className="mb-6">
        <h1 className="text-[22px] font-semibold tracking-tight">RAG 召回测试</h1>
        <p className="mt-1.5 max-w-[720px] text-[12px] leading-relaxed text-muted">
          一次看全四个阶段:检索没找到内容时,能判断到底是切分坏了、排序坏了,还是过滤把正确结果滤掉了。
        </p>
        <a
          href="/"
          className="mt-2 inline-block text-[12px] text-accent transition-opacity hover:opacity-80"
        >
          ← 返回工作台
        </a>
      </header>

      <div className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel p-2 shadow-soft">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-line bg-canvas px-3 py-2 text-[12px] outline-none transition-colors placeholder:text-muted/70 focus:border-accent/60"
          placeholder="输入检索问题"
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="shrink-0 rounded-lg bg-accent px-5 py-2 text-[12px] font-medium text-white shadow-soft transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "检索中…" : "开始检索"}
        </button>
      </div>

      {error ? (
        <p className="mb-4 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[12px] text-danger">
          {error}
        </p>
      ) : null}
      {trace ? <RecallStages trace={trace} /> : null}
    </main>
  );
}