import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 对齐 img_01 的浅色工作台配色
        canvas: "#f6f7f9",
        panel: "#ffffff",
        ink: "#1f2933",
        muted: "#6b7280",
        line: "#e5e7eb",
        accent: "#14b8a6",
      },
    },
  },
  plugins: [],
};

export default config;