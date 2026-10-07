"use client";

import { useEffect, useState } from "react";

import EvalReport from "@/components/EvalReport";
import { api } from "@/lib/api";
import type { EvalResult } from "@/lib/types";

export default function EvalsPage() {
  const [result, setResult] = useState<EvalResult | null>(null);
  const [history, setHistory] = useState<Record<string, any>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadHistory = async () => {
    try {
      setHistory(await api.evalRuns());
    } catch {
      /* 历史拿不到不影响跑评测 */
    }
  };

  useEffect(() => {
    void loadHistory();
  }, []);

  const run = async () => {
    setBusy(true);
    try {
      // 不传 mode:由服务端按当前 LLM_MODE 决定,
      // 写死 mock 会让真实模型的运行被贴上 mock 标签
      setResult(await api.runEval());
      setError("");
      await loadHistory();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1100px] p-8">
      <header className="mb-6">
        <h1 className="text-[22px] font-semibold tracking-tight">Evals</h1>
        <p className="mt-1.5 max-w-[720px] text-[12px] leading-relaxed text-muted">
          固定评测集 + 硬规则检查。改动 Prompt、检索配置或工具逻辑后复跑同一组题,对比改善与退步。
        </p>
        <a
          href="/"
          className="mt-2 inline-block text-[12px] text-accent transition-opacity hover:opacity-80"
        >
          ← 返回工作台
        </a>
      </header>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="rounded-lg bg-accent px-5 py-2 text-[12px] font-medium text-white shadow-soft transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "评测中…" : "运行评测"}
        </button>
        <span className="rounded-md bg-sunken px-2 py-1 text-[11px] text-muted">
          mock 模式下 ragas 会显式跳过,不会用假数字充数
        </span>
      </div>

      {error ? (
        <p className="mb-4 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[12px] text-danger">
          {error}
        </p>
      ) : null}
      {result ? <EvalReport result={result} /> : null}

      {history.length ? (
        <section className="mt-8">
          <h2 className="mb-2.5 text-[14px] font-semibold tracking-tight">历史运行</h2>
          <div className="overflow-hidden rounded-xl border border-line bg-panel">
            <table className="w-full border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-line bg-sunken text-left text-muted">
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">模式</th>
                  <th className="px-3 py-2 font-medium">通过</th>
                  <th className="px-3 py-2 font-medium">失败</th>
                  <th className="px-3 py-2 font-medium">ragas</th>
                </tr>
              </thead>
              <tbody>
                {history.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-line transition-colors last:border-0 hover:bg-hover"
                  >
                    <td className="px-3 py-2 tabular-nums">{run.id}</td>
                    <td className="px-3 py-2">{run.mode}</td>
                    <td className="px-3 py-2 tabular-nums">{run.passed}</td>
                    <td className="px-3 py-2 tabular-nums">{run.failed}</td>
                    <td className="px-3 py-2">{run.metrics?.ragas ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </main>
  );
}