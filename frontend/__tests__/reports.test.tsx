import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const reports = vi.fn();
const report = vi.fn();
const generateReport = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    reports: (...args: unknown[]) => reports(...args),
    report: (...args: unknown[]) => report(...args),
    generateReport: (...args: unknown[]) => generateReport(...args),
  },
}));

import ReportsPanel from "@/components/ReportsPanel";

const PAYLOAD = {
  total: 1,
  items: [
    {
      id: 1,
      period_key: "2026-W41",
      trigger: "auto",
      path: "docs/weekly-20261006.md",
      summary: "未处理 Issue 4 条、已合并 PR 1 条、失败 CI 1 次",
      open_issues: 4,
      merged_prs: 1,
      failed_ci: 1,
      generated_at: "2026-10-06T00:00:00Z",
    },
  ],
  scheduler: { enabled: true, check_seconds: 3600, days: 7, current_period: "2026-W41" },
};

describe("周报面板", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reports.mockResolvedValue(PAYLOAD);
  });

  test("列出周报并标出是自动还是手动生成", async () => {
    render(<ReportsPanel repoId={1} />);
    // 周期标识会出现两次:调度配置里一次、列表项里一次 —— 所以用 getAllByText
    await waitFor(() => expect(screen.getAllByText("2026-W41").length).toBeGreaterThan(0));
    expect(screen.getByText("自动")).toBeTruthy();
    expect(screen.getByText(/未处理 Issue 4 条/)).toBeTruthy();
  });

  test("把调度配置显示出来,而不是让周报凭空出现", async () => {
    render(<ReportsPanel repoId={1} />);
    await waitFor(() => expect(screen.getByText(/每/)).toBeTruthy());
    // 「已开启 / 每 N 分钟检查一次 / 统计窗口 N 天」都是用户判断周报可信度的依据
    expect(screen.getByText(/60 分钟检查一次/)).toBeTruthy();
  });

  test("接口失败时显示错误而不是空白", async () => {
    reports.mockRejectedValue(new Error("周报接口 500"));
    render(<ReportsPanel repoId={1} />);
    await waitFor(() => expect(screen.getByText(/周报接口 500/)).toBeTruthy());
  });
});