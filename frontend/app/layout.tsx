import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DevFlow AI — 多智能体研发协作助手",
  description: "分析 Issue、审查 PR、排查 CI 失败的研发协作助手",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}