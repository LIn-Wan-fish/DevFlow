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
    <main className="mx-auto max-w-[1100px] p-6">
      <header className="mb-4">
        <h1 className="text-[18px] font-semibold">Evals</h1>
        <p className="mt-1 text-[12px] text-muted">
          固定评测集 + 硬规则检查。改动 Prompt、检索配置或工具逻辑后复跑同一组题,对比改善与退步。
        </p>
        <a href="/" className="text-[12px] text-accent hover:underline">
          ← 返回工作台
        </a>
      </header>

      <div className="mb-4 flex items-center gap-3">
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="rounded bg-accent px-4 py-1.5 text-[12px] text-white disabled:opacity-40"
        >
          {busy ? "评测中…" : "运行评测"}
        </button>
        <span className="text-[11px] text-muted">
          mock 模式下 ragas 会显式跳过,不会用假数字充数
        </span>
      </div>

      {error ? <p className="mb-3 text-[12px] text-danger">{error}</p> : null}
      {result ? <EvalReport result={result} /> : null}

      {history.length ? (
        <section className="mt-6">
          <h2 className="mb-2 text-[13px] font-semibold">历史运行</h2>
          <table className="w-full border-collapse text-[11px]">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="py-1">#</th>
                <th>模式</th>
                <th>通过</th>
                <th>失败</th>
                <th>ragas</th>
              </tr>
            </thead>
            <tbody>
              {history.map((run) => (
                <tr key={run.id} className="border-b border-line">
                  <td className="py-1">{run.id}</td>
                  <td>{run.mode}</td>
                  <td>{run.passed}</td>
                  <td>{run.failed}</td>
                  <td>{run.metrics?.ragas ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </main>
  );
}