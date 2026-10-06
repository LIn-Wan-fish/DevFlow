import type { Config } from "tailwindcss";

const withVar = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  // 切 <html class="dark"> 而不是跟着系统走:用户要能自己选,
  // 系统偏好只是**默认值**(见 lib/theme.ts)。
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 全部指向 CSS 变量(见 globals.css),明暗两套值定义在那里。
        // 用 <alpha-value> 才能继续写 bg-ink/10 这类透明度修饰符。
        canvas: withVar("--canvas"),
        panel: withVar("--panel"),
        ink: withVar("--ink"),
        muted: withVar("--muted"),
        line: withVar("--line"),
        accent: withVar("--accent"),
        hover: withVar("--hover"),

        // 状态色。原先散落着 bg-amber-50 / text-red-600 这类调色板写法,
        // 深色模式下会变成刺眼的白斑 —— 统一收到语义名上。
        danger: withVar("--danger"),
        "danger-soft": withVar("--danger-soft"),
        ok: withVar("--ok"),
        "ok-soft": withVar("--ok-soft"),
        warn: withVar("--warn"),
        "warn-soft": withVar("--warn-soft"),
        info: withVar("--info"),
        "info-soft": withVar("--info-soft"),
      },
    },
  },
  plugins: [],
};

export default config;