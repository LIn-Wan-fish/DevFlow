"use client";

import type { EvalResult } from "@/lib/types";

/** 评测报告:通过率 + 逐题规则明细。 */
export function EvalReport({ result }: { result: EvalResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-soft">
        <span className="text-[26px] font-semibold leading-none tracking-tight tabular-nums">
          {result.passed}/{result.total}
        </span>
        <span className="text-[11px] text-muted">硬规则通过率</span>
        <span className="ml-auto rounded-md bg-sunken px-2 py-1 text-[11px] text-muted">
          ragas: {result.metrics?.ragas ?? "-"}
        </span>
      </div>

      <ul className="space-y-2">
        {result.cases.map((item) => (
          <li
            key={item.key}
            className="rounded-xl border border-line bg-panel p-3 shadow-soft transition-all hover:border-accent/40 hover:shadow-card"
          >
            <div className="flex items-center gap-2">
              <span
                className={`shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium ${
                  item.passed
                    ? "bg-ok-soft text-ok"
                    : "bg-danger-soft text-danger"
                }`}
              >
                {item.passed ? "PASS" : "FAIL"}
              </span>
              <span className="shrink-0 text-[12px] font-medium">{item.key}</span>
              <span className="ml-auto truncate text-[11px] text-muted">{item.question}</span>
            </div>
            <ul className="mt-2 space-y-1">
              {item.rule_results.map((rule, index) => (
                <li
                  key={index}
                  className={`text-[10px] leading-relaxed ${rule.passed ? "text-muted" : "text-danger"}`}
                >
                  <span className={rule.passed ? "text-ok" : "text-danger"}>
                    {rule.passed ? "✓" : "✗"}
                  </span>{" "}
                  {rule.rule}
                  {rule.passed ? "" : ` — ${rule.detail}`}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default EvalReport;