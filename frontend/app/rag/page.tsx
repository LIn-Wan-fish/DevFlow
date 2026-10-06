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
    <main className="mx-auto max-w-[1400px] p-6">
      <header className="mb-4">
        <h1 className="text-[18px] font-semibold">RAG 召回测试</h1>
        <p className="mt-1 text-[12px] text-muted">
          一次看全四个阶段:检索没找到内容时,能判断到底是切分坏了、排序坏了,还是过滤把正确结果滤掉了。
        </p>
        <a href="/" className="text-[12px] text-accent hover:underline">
          ← 返回工作台
        </a>
      </header>

      <div className="mb-4 flex gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="w-[420px] rounded border border-line px-3 py-1.5 text-[12px]"
          placeholder="输入检索问题"
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="rounded bg-accent px-4 py-1.5 text-[12px] text-white disabled:opacity-40"
        >
          {busy ? "检索中…" : "开始检索"}
        </button>
      </div>

      {error ? <p className="mb-3 text-[12px] text-danger">{error}</p> : null}
      {trace ? <RecallStages trace={trace} /> : null}
    </main>
  );
}