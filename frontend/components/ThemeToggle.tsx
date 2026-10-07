"use client";

import { useEffect, useState } from "react";

import { applyTheme, resolveTheme, saveTheme, type Theme } from "@/lib/theme";

/** 明暗切换。挂载后再读真实值 —— 服务端渲染时没有 localStorage。 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(resolveTheme());
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
    saveTheme(next);
  };

  return (
    <button
      onClick={toggle}
      title={theme === "dark" ? "切换到浅色" : "切换到深色"}
      aria-label={theme === "dark" ? "切换到浅色" : "切换到深色"}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-[12px] text-muted transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent"
    >
      {theme === "dark" ? "☀" : "☾"}
    </button>
  );
}