/**
 * 主题切换。
 *
 * 默认跟随**系统偏好**,但一旦用户手动选过就以他的选择为准 ——
 * 系统偏好只是默认值,不该覆盖用户显式操作。
 *
 * 真正防闪烁的地方在 `app/layout.tsx` 里的内联脚本:它在 React 接管之前
 * 就把 class 打上,否则首屏会先亮后暗闪一下。
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "devflow-theme";

/** 从存储里读用户的选择;没存过则跟随系统。 */
export function resolveTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // 隐私模式下 localStorage 可能不可用 —— 记住不了就记住不了,不影响使用
  }
}

/**
 * 供 layout 内联脚本使用的**最小**逻辑(字符串形式)。
 * 这里刻意不引用上面的函数:内联脚本在打包产物之外执行,引用不到模块。
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{
var k=${JSON.stringify(THEME_STORAGE_KEY)};
var s=localStorage.getItem(k);
var d=s==="dark"||(!s&&window.matchMedia("(prefers-color-scheme: dark)").matches);
if(d){document.documentElement.classList.add("dark");document.documentElement.dataset.theme="dark";}
}catch(e){}})();`;