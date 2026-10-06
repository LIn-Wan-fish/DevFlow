import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import DraftCard from "@/components/DraftCard";
import IssueList from "@/components/IssueList";
import MemoryPanel from "@/components/MemoryPanel";
import type { Draft, IssueItem } from "@/lib/types";

const ISSUES: IssueItem[] = [
  {
    id: 3,
    number: 3,
    title: "Feature: 增加桌面化能力",
    state: "open",
    group: "unarchived",
    labels: ["feature"],
    assignee: null,
    excerpt: "希望桌面化",
  },
];

describe("右栏 Issue 列表", () => {
  test("按分组计数展示", () => {
    render(
      <IssueList
        items={ISSUES}
        groups={{ unarchived: 2, discussing: 0, pending_decision: 0, handled: 0, rejected: 0, closed: 0 }}
      />,
    );
    expect(screen.getByText("未归档")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/增加桌面化能力/)).toBeInTheDocument();
  });
});

describe("草稿确认卡片", () => {
  test("确认后调用接口", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const draft: Draft = {
      id: 7,
      action: "comment_on_issue",
      target: "issue#3",
      preview: "进展如何?",
      risk_level: "low",
      status: "pending",
      requested_by_role: "member",
    };
    render(<DraftCard draft={draft} onConfirm={onConfirm} onReject={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /确认执行/ }));
    expect(onConfirm).toHaveBeenCalledWith(7);
  });

  test("高风险草稿默认不可直接执行", () => {
    const draft: Draft = {
      id: 8,
      action: "close_issue",
      target: "issue#3",
      preview: "将关闭 issue#3",
      risk_level: "high",
      status: "pending",
      requested_by_role: "member",
    };
    render(<DraftCard draft={draft} onConfirm={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("高风险")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认执行/ })).toBeDisabled();
  });

  test("高风险勾选风险确认后才可执行", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const draft: Draft = {
      id: 9,
      action: "close_issue",
      target: "issue#3",
      preview: "x",
      risk_level: "high",
      status: "pending",
      requested_by_role: "member",
    };
    render(<DraftCard draft={draft} onConfirm={onConfirm} onReject={vi.fn()} />);
    await userEvent.click(screen.getByLabelText(/我已确认风险/));
    expect(screen.getByRole("button", { name: /确认执行/ })).toBeEnabled();
  });
});

describe("记忆面板", () => {
  test("候选需批准后才出现在已生效区", () => {
    render(
      <MemoryPanel
        candidates={[{ id: 1, content: "CI 需要先跑 migrate", confidence: 0.8, status: "pending", run_id: 12 }]}
        entries={[]}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByText(/CI 需要先跑 migrate/)).toBeInTheDocument();
    expect(screen.queryByText(/已生效/)).not.toBeInTheDocument();
  });

  test("已生效记忆单独成区", () => {
    render(
      <MemoryPanel
        candidates={[]}
        entries={[{ id: 5, content: "已确认的经验", approved_by: "member", source_candidate_id: 1 }]}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByText(/已生效/)).toBeInTheDocument();
    expect(screen.getByText(/已确认的经验/)).toBeInTheDocument();
  });
});