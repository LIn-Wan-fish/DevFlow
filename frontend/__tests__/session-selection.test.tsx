import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import ProjectSidebar, { type SessionNode } from "@/components/ProjectSidebar";

// 两个项目下都有叫「默认会话」的会话 —— 这正是这个 bug 的触发条件
const SESSIONS: SessionNode[] = [
  { id: 1, title: "默认会话", age: "当前" },
  { id: 2, title: "第二个会话测试", age: "5 天" },
];

function renderSidebar(activeRepoId: number, activeSession: string, onSelect = vi.fn()) {
  render(
    <ProjectSidebar
      repos={[
        { id: 1, owner: "acme", name: "clowder-ai", full_name: "acme/clowder-ai", default_branch: "main", is_github: false },
        { id: 2, owner: "LIn-Wan-fish", name: "portfolio-demo", full_name: "LIn-Wan-fish/portfolio-demo", default_branch: "master", is_github: true },
      ]}
      activeRepoId={activeRepoId}
      sessions={SESSIONS}
      activeSession={activeSession}
      onSelectRepo={vi.fn()}
      onSelectSession={onSelect}
      onRefresh={vi.fn()}
      onAddProject={vi.fn()}
    />,
  );
  return onSelect;
}

/** 选中的会话用的是 accent 色,未选中是 muted。 */
function highlighted(): string[] {
  return screen
    .getAllByRole("button")
    .filter((b) => b.className.includes("text-accent"))
    .map((b) => b.textContent ?? "");
}

describe("会话选中态", () => {
  test("同名会话只点亮当前项目下的那一个", () => {
    // 回归:选中态原先按**标题**判定,两个项目都有「默认会话」-> 同时点亮。
    renderSidebar(1, "1:1");
    const on = highlighted().filter((t) => t.includes("默认会话"));
    expect(on).toHaveLength(1);
  });

  test("切到另一个项目后点亮的是它自己的同名会话", () => {
    renderSidebar(2, "2:1");
    const on = highlighted().filter((t) => t.includes("默认会话"));
    expect(on).toHaveLength(1);
  });

  test("点会话回传的是 id 而不是标题", () => {
    // 回传标题的话,两个项目的同名会话在后端也会落进同一段历史
    const onSelect = renderSidebar(1, "1:1");
    return userEvent
      .click(screen.getAllByText("第二个会话测试")[0])
      .then(() => expect(onSelect).toHaveBeenCalledWith(2));
  });

  test("另一个项目的同名会话不会被点亮", () => {
    // 选中 1:1 时,2:1 必须是未选中态
    renderSidebar(1, "1:1");
    const buttons = screen.getAllByRole("button");
    const all = buttons.filter((b) => (b.textContent ?? "").includes("默认会话"));
    expect(all).toHaveLength(2);
    expect(all.filter((b) => b.className.includes("text-accent"))).toHaveLength(1);
  });
});
