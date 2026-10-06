"use client";

/**
 * 面板之间的拖拽手柄。
 *
 * 做得**比看起来宽**:视觉上是 1px 的线,实际热区 7px 并往两侧各扩 3px ——
 * 否则那条线太细,鼠标很难精准停在上面(这是拖拽手感好坏的关键)。
 */
export default function ResizeHandle({
  handlers,
  resizing,
  label,
}: {
  handlers: Record<string, unknown>;
  resizing: boolean;
  label: string;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      title={`拖动调整宽度(双击复位)`}
      className={`group relative z-10 w-[7px] shrink-0 cursor-col-resize ${
        resizing ? "bg-accent/40" : "bg-transparent hover:bg-accent/30"
      }`}
      {...handlers}
    >
      {/* 视觉上的分割线,只有 1px;热区靠外层撑开 */}
      <span className="pointer-events-none absolute inset-y-0 left-[3px] w-px bg-line" />
    </div>
  );
}