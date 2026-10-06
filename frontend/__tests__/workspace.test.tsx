import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import OverviewBar from "@/components/OverviewBar";
import type { Health } from "@/lib/types";

const HEALTH: Health = {
  repo: "acme/clowder-ai",
  open_issues: 2,
  prs_pending_review: 0,
  issues_resolved: 0,
  issues_rejected: 0,
  failed_ci: 1,
  merged_prs: 1,
};

describe("总览统计条", () => {
  test("渲染六个统计卡片", () => {
    render(<OverviewBar health={HEALTH} repo="acme/clowder-ai" session="默认会话" />);
    for (const label of [
      "待处理 Issue",
      "待 Review PR",
      "已处理 Issue",
      "已拒绝 Issue",
      "失败 CI",
      "已合并 PR",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  test("统计数字来自 props 而不是写死", () => {
    render(
      <OverviewBar
        health={{ ...HEALTH, open_issues: 7, failed_ci: 4 }}
        repo="r"
        session="s"
      />,
    );
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  test("展示仓库与会话标识", () => {
    render(<OverviewBar health={HEALTH} repo="acme/clowder-ai" session="默认会话" />);
    expect(screen.getByText("acme/clowder-ai")).toBeInTheDocument();
    expect(screen.getByText(/默认会话/)).toBeInTheDocument();
  });
});