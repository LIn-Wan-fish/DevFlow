"use client";

import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * 流式输出时,最后一段很可能是**没写完的 markdown** —— 最典型的是代码块:
 * 开头的围栏已经吐出来了,收尾的还没。这时 react-markdown 会把后面的内容
 * 全当成代码,界面先闪一大块代码、等下一条消息才恢复排版。
 *
 * 这里在渲染前补一个收尾围栏,让中间态也稳定。**只影响渲染,不改动原始文本**。
 */
export function closeOpenFence(text: string): string {
  const fences = (text.match(/^\s*```/gm) ?? []).length;
  return fences % 2 === 1 ? text + "\n```" : text;
}

/**
 * 行内代码 vs 代码块。
 * react-markdown v9 之后不再给 `inline` 标记,只能自己判断:
 * 有 language- 类名、或内容跨行,就是代码块。
 */
function isBlockCode(className: unknown, children: ReactNode): boolean {
  if (typeof className === "string" && className.startsWith("language-")) return true;
  return String(children ?? "").includes("\n");
}

const COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mt-3 mb-1.5 text-[15px] font-semibold first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-3 mb-1.5 text-[14px] font-semibold first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-2.5 mb-1 text-[13px] font-semibold first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-2 mb-1 text-[12px] font-semibold first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed [&>p]:my-0">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer"
       className="text-info underline underline-offset-2 hover:text-info">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-line pl-3 text-muted">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-line" />,
  // 代码块:横向可滚动,不折行 —— 折行会把代码结构弄乱
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded border border-line bg-ink/[0.04] p-2.5
                    font-mono text-[11px] leading-relaxed">{children}</pre>
  ),
  code: ({ className, children, ...props }) =>
    isBlockCode(className, children) ? (
      <code className={(className ?? "") + " font-mono"} {...props}>{children}</code>
    ) : (
      <code className="rounded bg-ink/10 px-1 py-0.5 font-mono text-[11px]" {...props}>
        {children}
      </code>
    ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[11px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-line bg-ink/[0.04] px-2 py-1 text-left font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="border border-line px-2 py-1 align-top">{children}</td>,
};

export default function Markdown({
  children,
  streaming = false,
}: {
  children: string;
  /** 还在流式输出中 —— 会对未闭合的代码围栏做兜底 */
  streaming?: boolean;
}) {
  return (
    // 不开 rehype-raw:react-markdown 默认只构建 React 元素、不走 innerHTML,
    // 原始 HTML 会被当纯文本转义。模型输出属于不可信内容,这条路必须一直关着。
    <div className="text-[12px] leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {streaming ? closeOpenFence(children) : children}
      </ReactMarkdown>
    </div>
  );
}
