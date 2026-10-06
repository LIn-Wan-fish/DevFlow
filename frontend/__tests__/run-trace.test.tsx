import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import RunTrace from "@/components/RunTrace";
import type { SseEvent } from "@/lib/types";

describe("执行轨迹", () => {
  test("按顺序展示规划 / 工具 / 任务", () => {
    const events: SseEvent[] = [
      { event: "plan", data: { tasks: [{ task_key: "t1", title: "梳理 Issue", depends_on: [] }] } },
      { event: "tool_call", data: { tool: "analyze_issue", args: { number: 24 } } },
      { event: "tool_result", data: { tool: "analyze_issue", summary: "优先级 P0" } },
    ];
    render(<RunTrace events={events} />);
    // 工具名在「调用」和「结果」两行各出现一次,所以断言存在而非唯一
    expect(screen.getAllByText("analyze_issue").length).toBeGreaterThan(0);
    expect(screen.getByText(/优先级 P0/)).toBeInTheDocument();
    expect(screen.getByText(/梳理 Issue/)).toBeInTheDocument();
  });

  test("草稿事件渲染确认按钮", () => {
    render(
      <RunTrace
        events={[{ event: "draft", data: { draft_id: 7, action: "comment_on_issue", target: "issue#3" } }]}
      />,
    );
    expect(screen.getByRole("button", { name: /确认/ })).toBeInTheDocument();
  });

  test("Observer 的冲突被红色列出", () => {
    render(
      <RunTrace
        events={[
          {
            event: "observation",
            data: { conflicts: ["PR #12 说可合,但 CI #512 失败"], gaps: ["缺少日志"] },
          },
        ]}
      />,
    );
    expect(screen.getByText(/PR #12 说可合/)).toBeInTheDocument();
    expect(screen.getByText(/缺少日志/)).toBeInTheDocument();
  });

  test("工具失败被显式标出而不是静默", () => {
    render(
      <RunTrace events={[{ event: "tool_result", data: { tool: "debug_ci", error: "上游不可用" } }]} />,
    );
    expect(screen.getByText(/上游不可用/)).toBeInTheDocument();
  });

  test("没有事件时不渲染", () => {
    const { container } = render(<RunTrace events={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
test("token 增量不进轨迹列表", () => {
  // 一次真实回答可能产生几百个 token 增量帧。轨迹是给人看的,不该被它刷屏;
  // 增量只用于拼出对话区的流式预览。
  render(
    <RunTrace
      events={[
        { event: "tool_call", data: { tool: "debug_ci", args: { number: 512 } } },
        { event: "token", data: { delta: "第" } },
        { event: "token", data: { delta: "一" } },
        { event: "token", data: { delta: "段" } },
        { event: "done", data: { stop_reason: "completed" } },
      ]}
    />,
  );
  expect(screen.queryByText("第")).toBeNull();
  expect(screen.queryByText("一")).toBeNull();
  expect(screen.queryByText(/token/)).toBeNull();
  // 非 token 事件仍然照常展示
  expect(screen.getByText(/debug_ci|CI/)).toBeTruthy();
});