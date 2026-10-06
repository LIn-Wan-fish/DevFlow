"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 可拖动面板宽度。
 *
 * 几个刻意的处理:
 * - 用 **pointer 事件**而不是 mouse:顺带支持触屏与手写笔
 * - `setPointerCapture`:鼠标拖出手柄甚至拖出窗口也不会丢跟踪
 * - 拖动时给 body 加类禁用选中,否则会把界面上的文字整片选中
 * - **夹取在 [min, max]**:拖到 0 宽会把面板彻底拖没,找不回来
 * - 双击复位:这是 VSCode 的习惯,顺手做一个
 */

export type PanelSide = "left" | "right";

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function usePanelWidth({
  storageKey,
  initial,
  min,
  max,
  side,
}: {
  storageKey: string;
  initial: number;
  min: number;
  max: number;
  side: PanelSide;
}) {
  const [width, setWidth] = useState(initial);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  // 首次挂载时读回上次的宽度。放在 effect 里而不是 useState 初始值中:
  // 服务端渲染时没有 localStorage,直接读会导致 hydration 不一致。
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved) setWidth(clamp(Number(saved) || initial, min, max));
    } catch {
      // localStorage 不可用就用默认宽度
    }
  }, [storageKey, initial, min, max]);

  const persist = useCallback(
    (value: number) => {
      try {
        window.localStorage.setItem(storageKey, String(value));
      } catch {
        // 存不下就算了,不影响本次会话
      }
    },
    [storageKey],
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      drag.current = { startX: event.clientX, startWidth: width };
      setResizing(true);
      document.body.classList.add("resizing");
      // 可选调用:jsdom 没有这个方法,个别元素在真机上也未必有实现
      event.currentTarget.setPointerCapture?.(event.pointerId);
    },
    [width],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!drag.current) return;
      const delta = event.clientX - drag.current.startX;
      // 右侧面板是往左拖变宽,方向相反
      const next = side === "left" ? drag.current.startWidth + delta : drag.current.startWidth - delta;
      setWidth(clamp(next, min, max));
    },
    [side, min, max],
  );

  const stop = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!drag.current) return;
      drag.current = null;
      setResizing(false);
      document.body.classList.remove("resizing");
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      setWidth((current) => {
        persist(current);
        return current;
      });
    },
    [persist],
  );

  /** 双击复位。不给"复位"入口的话,拖窄了就只能靠手拖回来。 */
  const onDoubleClick = useCallback(() => {
    setWidth(initial);
    persist(initial);
  }, [initial, persist]);

  return { width, resizing, handlers: { onPointerDown, onPointerMove, onPointerUp: stop, onPointerCancel: stop, onDoubleClick } };
}