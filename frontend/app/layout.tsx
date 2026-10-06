import type { Metadata } from "next";

import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "DevFlow AI — 多智能体研发协作助手",
  description: "分析 Issue、审查 PR、排查 CI 失败的研发协作助手",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/*
          防主题闪烁。这段脚本必须在 React 接管**之前**跑完:
          否则深色模式下会先渲染一帧亮色界面再翻过来,肉眼可见地闪一下。
          用 dangerouslySetInnerHTML 是 Next 官方推荐的写法 ——
          内联脚本要同步执行,用组件包起来就晚了。
        */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}