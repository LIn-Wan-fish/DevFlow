import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import Markdown, { closeOpenFence } from "@/components/Markdown";

// 模型输出属于**不可信内容**,这段专门用来验它不会被当成 HTML 执行
const XSS_PAYLOAD = `<img src=x onerror="window.__pwned=1" /><script>window.__pwned=2</script>`;

describe("Markdown 渲染", () => {
  test("把 markdown 渲染成元素,而不是原样输出符号", () => {
    render(<Markdown>{"## 结论\n\n**CI #512 失败**\n\n- 第一项\n- 第二项"}</Markdown>);
    // 标题变成真正的 heading,加粗不再是字面的 **
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("结论");
    expect(screen.getByText("CI #512 失败").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  test("表格渲染成 table(靠 remark-gfm)", () => {
    render(<Markdown>{"| 关键词 | 结果 |\n|---|---|\n| 量子 | 未找到 |"}</Markdown>);
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "关键词" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "未找到" })).toBeTruthy();
  });

  test("行内代码与代码块都渲染成 code", () => {
    render(<Markdown>{"用 `refresh_token` 换新令牌:\n\n```python\nprint(1)\n```"}</Markdown>);
    const codes = screen.getAllByText(/refresh_token|print\(1\)/);
    expect(codes.length).toBe(2);
    for (const el of codes) expect(el.tagName).toBe("CODE");
  });

  test("链接在新标签打开且带 noreferrer", () => {
    render(<Markdown>{"[文档](https://example.com/a)"}</Markdown>);
    const link = screen.getByRole("link", { name: "文档" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noreferrer");
  });

  test("原始 HTML 不会被执行 —— 模型输出属于不可信内容", () => {
    const { container } = render(<Markdown>{XSS_PAYLOAD}</Markdown>);
    // 刻意不开 rehype-raw:react-markdown 默认只构建 React 元素、不走 innerHTML
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    // 但内容仍以文本形式可见,不是被静默吞掉
    expect(container.textContent).toContain("onerror");
  });
});

describe("流式输出时的半截 markdown", () => {
  test("未闭合的代码围栏会被补上收尾", () => {
    // 模型刚吐出开头的围栏,收尾的还没来 —— 不补的话后面全部会被当成代码
    expect(closeOpenFence("```python\nprint(1)")).toBe("```python\nprint(1)\n```");
  });

  test("已经闭合的围栏不会被动", () => {
    const text = "```python\nprint(1)\n```";
    expect(closeOpenFence(text)).toBe(text);
  });

  test("没有围栏时原样返回", () => {
    const text = "普通一句话";
    expect(closeOpenFence(text)).toBe(text);
  });

  test("多个成对围栏不会被动", () => {
    const text = "```a\n1\n```\n中间\n```b\n2\n```";
    expect(closeOpenFence(text)).toBe(text);
  });

  test("组件在 streaming 下也不抛错", () => {
    render(<Markdown streaming>{"结论如下:\n\n```python\nprint(1)"}</Markdown>);
    expect(screen.getByText("print(1)").tagName).toBe("CODE");
  });
});
