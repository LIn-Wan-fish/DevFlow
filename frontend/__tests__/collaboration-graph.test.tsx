import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import CollaborationGraph, { layout, type Finding } from "@/components/CollaborationGraph";

function f(id: number, references: number[] = [], extra: Partial<Finding> = {}): Finding {
  return {
    id, author: `agent${id}`, topic: `topic${id}`, conclusion: `结论${id}`,
    confidence: 0.7, status: "confirmed", references, supersedes_id: null,
    created_at: null, ...extra,
  };
}

describe("协作图分层", () => {
  test("无引用的排在第 0 层", () => {
    const pos = layout([f(1), f(2)]);
    expect(pos.get(1)!.col).toBe(0);
    expect(pos.get(2)!.col).toBe(0);
  });

  test("引用别人就往后排一层", () => {
    // 综合节点引用三条发现 -> 应当在第 1 层,而不是和它们并排
    const pos = layout([f(1), f(2), f(3), f(10, [1, 2, 3])]);
    expect([1, 2, 3].map((i) => pos.get(i)!.col)).toEqual([0, 0, 0]);
    expect(pos.get(10)!.col).toBe(1);
  });

  test("链式引用逐层递进", () => {
    const pos = layout([f(1), f(2, [1]), f(3, [2])]);
    expect([pos.get(1)!.col, pos.get(2)!.col, pos.get(3)!.col]).toEqual([0, 1, 2]);
  });

  test("同层内不重叠", () => {
    const pos = layout([f(1), f(2), f(3)]);
    expect(new Set([1, 2, 3].map((i) => pos.get(i)!.row)).size).toBe(3);
  });

  test("引用不存在的 id 不会崩", () => {
    // 数据可能不完整(比如引用了别的运行里的发现),不能因此白屏
    const pos = layout([f(1, [999])]);
    expect(pos.get(1)!.col).toBe(0);
  });

  test("有环也不会死循环", () => {
    const pos = layout([f(1, [2]), f(2, [1])]);
    expect(pos.size).toBe(2);
  });
});

// vi.mock 会被**提升**到文件顶部,所以桩必须用 vi.hoisted 先建好 ——
// 写成普通的 const,工厂执行时它还没初始化(实测报 findings is not defined)。
const findings = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  api: { findings: (...a: unknown[]) => findings(...a) },
}));

describe("协作图组件", () => {
  beforeEach(() => vi.clearAllMocks());

  test("没有 run_id 时不渲染", () => {
    const { container } = render(<CollaborationGraph runId={null} />);
    expect(container.textContent).toBe("");
    expect(findings).not.toHaveBeenCalled();
  });

  test("画出节点、边与统计", async () => {
    findings.mockResolvedValue({
      run_id: 9,
      findings: [f(1), f(2), f(10, [1, 2])],
      active_finding_ids: [1, 2, 10],
      edges: [{ from: 10, to: 1 }, { from: 10, to: 2 }],
      conflicts: [],
      authors: ["agent1", "agent2", "agent10"],
    });
    const { container } = render(<CollaborationGraph runId={9} />);
    await waitFor(() => expect(screen.getByText("协作图")).toBeTruthy());
    expect(container.querySelectorAll("rect")).toHaveLength(3);
    expect(container.querySelectorAll("path[marker-end]")).toHaveLength(2);
    expect(screen.getByText(/3 条发现 · 2 条引用 · 3 个 Agent/)).toBeTruthy();
  });

  test("有分歧时显式提示,而不是悄悄带过", async () => {
    findings.mockResolvedValue({
      run_id: 9,
      findings: [f(1, [], { topic: "pr #12", author: "pr_review_agent" }),
                 f(2, [], { topic: "pr #12", author: "ci_debug_agent" })],
      active_finding_ids: [1, 2],
      edges: [],
      conflicts: [{ topic: "pr #12", authors: ["pr_review_agent", "ci_debug_agent"],
                    conclusions: ["可合入", "失败"] }],
      authors: ["pr_review_agent", "ci_debug_agent"],
    });
    render(<CollaborationGraph runId={9} />);
    await waitFor(() => expect(screen.getByText(/分歧「pr #12」/)).toBeTruthy());
    expect(screen.getByText(/需要人工判断/)).toBeTruthy();
  });

  test("没有发现时整个不渲染", async () => {
    // 普通问答(单工具路径)本来就不会产生发现。给它一个空盒子是噪音 ——
    // 实测用户会以为"协作图坏了",而不是意识到"这次本来就没有协作"。
    findings.mockResolvedValue({ run_id: 9, findings: [], active_finding_ids: [],
                                 edges: [], conflicts: [], authors: [] });
    const { container } = render(<CollaborationGraph runId={9} />);
    await waitFor(() => expect(findings).toHaveBeenCalled());
    await waitFor(() => expect(container.textContent).toBe(""));
  });

  test("接口失败时显示原因", async () => {
    findings.mockRejectedValue(new Error("404"));
    render(<CollaborationGraph runId={9} />);
    await waitFor(() => expect(screen.getByText(/协作图加载失败/)).toBeTruthy());
  });
});
