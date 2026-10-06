"use client";

import type { EvalResult } from "@/lib/types";

/** 评测报告:通过率 + 逐题规则明细。 */
export function EvalReport({ result }: { result: EvalResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded border border-line bg-panel px-3 py-2">
        <span className="text-[16px] font-semibold">
          {result.passed}/{result.total}
        </span>
        <span className="text-[11px] text-muted">硬规则通过率</span>
        <span className="ml-auto text-[11px] text-muted">
          ragas: {result.metrics?.ragas ?? "-"}
        </span>
      </div>

      <ul className="space-y-2">
        {result.cases.map((item) => (
          <li key={item.key} className="rounded border border-line bg-panel p-2">
            <div className="flex items-center gap-2">
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] ${
                  item.passed
                    ? "bg-ok-soft text-ok"
                    : "bg-danger-soft text-danger"
                }`}
              >
                {item.passed ? "PASS" : "FAIL"}
              </span>
              <span className="text-[12px] font-medium">{item.key}</span>
              <span className="ml-auto truncate text-[11px] text-muted">{item.question}</span>
            </div>
            <ul className="mt-1 space-y-0.5">
              {item.rule_results.map((rule, index) => (
                <li key={index} className="text-[10px] text-muted">
                  {rule.passed ? "✓" : "✗"} {rule.rule}
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