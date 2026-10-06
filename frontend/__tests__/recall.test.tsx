import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import EvalReport from "@/components/EvalReport";
import RecallStages from "@/components/RecallStages";
import type { EvalResult, RecallTrace } from "@/lib/types";

describe("召回测试", () => {
  test("并列展示四个阶段", () => {
    const trace: RecallTrace = {
      query: "登录接口变更",
      chunks: [{ chunk_id: 1, doc_path: "docs/api.md", heading_path: "登录接口 > v1.2 变更", preview: "..." }],
      vector_hits: [],
      keyword_hits: [],
      fused_reranked: [],
    };
    render(<RecallStages trace={trace} />);
    for (const label of ["切分", "向量召回", "关键词召回", "RRF 融合 + 重排"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

describe("评测报告", () => {
  test("展示通过率与逐题规则", () => {
    const result: EvalResult = {
      eval_run_id: 1,
      total: 10,
      passed: 10,
      failed: 0,
      metrics: { ragas: "skipped (mock mode)" },
      cases: [
        {
          key: "ci-512-rootcause",
          question: "CI #512 为什么失败?",
          passed: true,
          rule_results: [{ rule: "expected_tool_called", passed: true, detail: "" }],
          actual: {},
        },
      ],
    };
    render(<EvalReport result={result} />);
    expect(screen.getByText("10/10")).toBeInTheDocument();
    expect(screen.getByText(/expected_tool_called/)).toBeInTheDocument();
    expect(screen.getByText(/skipped \(mock mode\)/)).toBeInTheDocument();
  });

  test("失败用例显示失败原因", () => {
    const result: EvalResult = {
      eval_run_id: 2,
      total: 1,
      passed: 0,
      failed: 1,
      metrics: { ragas: "skipped (mock mode)" },
      cases: [
        {
          key: "pr-12-review",
          question: "PR #12 能不能合?",
          passed: false,
          rule_results: [
            { rule: "expected_tool_called", passed: false, detail: "期望调用 review_pr" },
          ],
          actual: {},
        },
      ],
    };
    render(<EvalReport result={result} />);
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText(/期望调用 review_pr/)).toBeInTheDocument();
  });
});