import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { applyTheme, resolveTheme, saveTheme, THEME_STORAGE_KEY } from "@/lib/theme";
import { clamp, usePanelWidth } from "@/lib/usePanelWidth";

/** 造一个 PointerEvent 形状的对象 —— jsdom 的 PointerEvent 支持不全。 */
function pointer(clientX: number, pointerId = 1) {
  return {
    clientX,
    pointerId,
    preventDefault: vi.fn(),
    currentTarget: { setPointerCapture: vi.fn(), releasePointerCapture: vi.fn() },
  } as unknown as React.PointerEvent<HTMLDivElement>;
}

describe("宽度夹取", () => {
  test("把宽度限制在范围内", () => {
    expect(clamp(50, 180, 420)).toBe(180);
    expect(clamp(999, 180, 420)).toBe(420);
    expect(clamp(300, 180, 420)).toBe(300);
  });
});

describe("可拖动面板", () => {
  beforeEach(() => window.localStorage.clear());

  test("左侧面板向右拖变宽", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w", initial: 248, min: 180, max: 420, side: "left" }));
    act(() => result.current.handlers.onPointerDown(pointer(100)));
    act(() => result.current.handlers.onPointerMove(pointer(160)));
    expect(result.current.width).toBe(308);
  });

  test("右侧面板方向相反:向左拖才变宽", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w", initial: 372, min: 280, max: 640, side: "right" }));
    act(() => result.current.handlers.onPointerDown(pointer(1000)));
    act(() => result.current.handlers.onPointerMove(pointer(940)));
    expect(result.current.width).toBe(432);
  });

  test("拖过头会被夹住,面板不会被拖没", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w", initial: 248, min: 180, max: 420, side: "left" }));
    act(() => result.current.handlers.onPointerDown(pointer(500)));
    act(() => result.current.handlers.onPointerMove(pointer(-5000)));
    expect(result.current.width).toBe(180);
    act(() => result.current.handlers.onPointerMove(pointer(5000)));
    expect(result.current.width).toBe(420);
  });

  test("松开后记住宽度", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w-keep", initial: 248, min: 180, max: 420, side: "left" }));
    act(() => result.current.handlers.onPointerDown(pointer(100)));
    act(() => result.current.handlers.onPointerMove(pointer(180)));
    act(() => result.current.handlers.onPointerUp(pointer(180)));
    expect(window.localStorage.getItem("w-keep")).toBe("328");
  });

  test("挂载时读回上次的宽度", () => {
    window.localStorage.setItem("w-restore", "333");
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w-restore", initial: 248, min: 180, max: 420, side: "left" }));
    expect(result.current.width).toBe(333);
  });

  test("存的值超出范围时也要夹回范围内", () => {
    window.localStorage.setItem("w-bad", "9999");
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w-bad", initial: 248, min: 180, max: 420, side: "left" }));
    expect(result.current.width).toBe(420);
  });

  test("双击复位到默认宽度", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w-reset", initial: 248, min: 180, max: 420, side: "left" }));
    act(() => result.current.handlers.onPointerDown(pointer(100)));
    act(() => result.current.handlers.onPointerMove(pointer(300)));
    expect(result.current.width).toBe(448 > 420 ? 420 : 448);
    act(() => result.current.handlers.onDoubleClick());
    expect(result.current.width).toBe(248);
    expect(window.localStorage.getItem("w-reset")).toBe("248");
  });

  test("拖动中给 body 加标记,松开后移除", () => {
    const { result } = renderHook(() =>
      usePanelWidth({ storageKey: "w", initial: 248, min: 180, max: 420, side: "left" }));
    act(() => result.current.handlers.onPointerDown(pointer(100)));
    expect(document.body.classList.contains("resizing")).toBe(true);
    act(() => result.current.handlers.onPointerUp(pointer(100)));
    expect(document.body.classList.contains("resizing")).toBe(false);
  });
});

describe("主题", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  function stubSystem(dark: boolean) {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: dark && query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  }

  test("没存过时跟随系统偏好", () => {
    stubSystem(true);
    expect(resolveTheme()).toBe("dark");
    stubSystem(false);
    expect(resolveTheme()).toBe("light");
  });

  test("用户手动选过就以他的选择为准,系统偏好不再覆盖", () => {
    stubSystem(true);
    saveTheme("light");
    expect(resolveTheme()).toBe("light");
  });

  test("applyTheme 切 html 上的 dark 类", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  test("存不进去也不该抛错(隐私模式)", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceeded");
    });
    expect(() => saveTheme("dark")).not.toThrow();
    spy.mockRestore();
  });
});
