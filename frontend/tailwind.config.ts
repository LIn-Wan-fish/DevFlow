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
        sunken: withVar("--sunken"),
        ink: withVar("--ink"),
        muted: withVar("--muted"),
        line: withVar("--line"),
        accent: withVar("--accent"),
        "accent-soft": withVar("--accent-soft"),
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
        // 中性徽章(上下文 / 引用)与「证据审查」用的紫。
        // 原先硬编码 bg-gray-100 / bg-purple-100,深色下是死值,不受主题控制。
        neutral: withVar("--neutral"),
        "neutral-soft": withVar("--neutral-soft"),
        violet: withVar("--violet"),
        "violet-soft": withVar("--violet-soft"),
      },

      // 卡片化之后圆角要跟着放大:6px 的圆角配阴影会显得局促
      borderRadius: {
        lg: "10px",
        xl: "14px",
        "2xl": "18px",
        "3xl": "22px",
      },

      // 阴影色跟着底色走暖调(见 --shadow),纯黑阴影在米白上会发脏
      boxShadow: {
        soft: "0 1px 2px rgb(var(--shadow) / 0.06)",
        card: "0 1px 2px rgb(var(--shadow) / 0.06), 0 4px 14px -6px rgb(var(--shadow) / 0.12)",
        pop: "0 18px 44px -14px rgb(var(--shadow) / 0.3), 0 2px 8px rgb(var(--shadow) / 0.1)",
      },

      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(2px)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.18s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
