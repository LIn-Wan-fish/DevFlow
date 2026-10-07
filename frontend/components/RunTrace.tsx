"use client";

import { useState } from "react";

import type { SseEvent } from "@/lib/types";

/**
 * 执行轨迹:规划 → 工具调用 → 任务状态 → 观察结论。
 *
 * 直接由 SSE 事件流驱动渲染,所以进度是「长出来」的,
 * 而不是等 done 之后一次性出现。
 */
export function RunTrace({
  events,
  onConfirmDraft,
  onRejectDraft,
}: {
  events: SseEvent[];
  onConfirmDraft?: (id: number) => void;
  onRejectDraft?: (id: number) => void;
}) {
  const [open, setOpen] = useState(true);
  const visible = (events || []).filter((event) => event.event !== "token");
  if (!visible.length) return null;

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-line bg-sunken">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[11px] font-semibold text-muted transition-colors hover:bg-hover hover:text-ink"
      >
        <span className="text-[9px]">{open ? "▾" : "▸"}</span>
        <span>执行轨迹</span>
        <span className="ml-auto rounded-md bg-panel px-1.5 py-0.5 text-[10px] font-normal tabular-nums">
          {visible.length} 个事件
        </span>
      </button>

      {open ? (
        <ol className="space-y-1 border-t border-line px-2.5 py-2" data-testid="run-trace">
          {visible.map((event, index) => (
            <TraceRow
              key={`${event.event}-${index}`}
              event={event}
              onConfirmDraft={onConfirmDraft}
              onRejectDraft={onRejectDraft}
            />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function TraceRow({
  event,
  onConfirmDraft,
  onRejectDraft,
}: {
  event: SseEvent;
  onConfirmDraft?: (id: number) => void;
  onRejectDraft?: (id: number) => void;
}) {
  const { event: kind, data } = event;

  if (kind === "plan") {
    const tasks = (data.tasks as any[]) ?? [];
    return (
      <li className="text-[11px]">
        <span className="mr-1.5 rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] text-accent">规划</span>
        {data.replan ? `重新规划(第 ${data.replan_count} 次)` : `拆出 ${tasks.length} 个任务`}
        <ul className="ml-4 mt-0.5 space-y-0.5 text-muted">
          {tasks.map((task) => (
            <li key={task.task_key}>
              {task.task_key} · {task.title}
              {task.depends_on?.length ? `(依赖 ${task.depends_on.join(",")})` : ""}
            </li>
          ))}
        </ul>
      </li>
    );
  }

  if (kind === "task_started") {
    return (
      <li className="text-[11px]">
        <span className="mr-1.5 rounded-md bg-warn-soft px-1.5 py-0.5 text-[10px] text-warn">执行中</span>
        {data.title ?? data.task_key}({data.agent})
      </li>
    );
  }

  if (kind === "task_finished") {
    const status = String(data.status ?? "");
    const color =
      status === "succeeded"
        ? "bg-ok-soft text-ok"
        : status === "skipped"
          ? "bg-neutral-soft text-neutral"
          : "bg-danger-soft text-danger";
    return (
      <li className="text-[11px]">
        <span className={`mr-1.5 rounded-md px-1.5 py-0.5 text-[10px] ${color}`}>{status}</span>
        {data.task_key}
        {data.error ? <span className="ml-1 text-danger">{data.error}</span> : null}
      </li>
    );
  }

  if (kind === "tool_call") {
    return (
      <li className="text-[11px]">
        <span className="mr-1.5 rounded-md bg-info-soft px-1.5 py-0.5 text-[10px] text-info">调用</span>
        <code>{data.tool}</code>
        {data.args && Object.keys(data.args).length ? (
          <span className="ml-1 text-muted">{JSON.stringify(data.args)}</span>
        ) : null}
      </li>
    );
  }

  if (kind === "tool_result") {
    if (data.error) {
      return (
        <li className="text-[11px] text-danger">
          <span className="mr-1.5 rounded-md bg-danger-soft px-1.5 py-0.5 text-[10px]">失败</span>
          <code>{data.tool}</code> — {data.error}
        </li>
      );
    }
    return (
      <li className="text-[11px]">
        <span className="mr-1.5 rounded-md bg-ok-soft px-1.5 py-0.5 text-[10px] text-ok">结果</span>
        <code>{data.tool}</code>
        <span className="ml-1 text-muted">{data.summary}</span>
      </li>
    );
  }

  if (kind === "observation") {
    const gaps = (data.gaps as string[]) ?? [];
    const conflicts = (data.conflicts as string[]) ?? [];
    return (
      <li className="text-[11px]">
        <span className="mr-1.5 rounded-md bg-violet-soft px-1.5 py-0.5 text-[10px] text-violet">证据审查</span>
        {conflicts.length ? (
          <ul className="ml-4 mt-0.5 list-disc space-y-0.5 text-danger">
            {conflicts.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        ) : (
          <span className="text-muted">未发现结论冲突</span>
        )}
        {gaps.length ? (
          <ul className="ml-4 mt-0.5 list-disc space-y-0.5 text-warn">
            {gaps.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        ) : null}
      </li>
    );
  }

  if (kind === "draft") {
    return (
      <li className="text-[11px]">
        <span className="mr-1 rounded bg-ink px-1 text-white">草稿</span>
        {data.action} → {data.target}
        <span className="ml-1 text-muted">等待人工确认</span>
        <span className="ml-2 inline-flex gap-1">
          <button
            type="button"
            onClick={() => onConfirmDraft?.(data.draft_id)}
            className="rounded bg-accent px-1.5 text-[10px] text-white"
          >
            确认
          </button>
          <button
            type="button"
            onClick={() => onRejectDraft?.(data.draft_id)}
            className="rounded border border-line px-1.5 text-[10px]"
          >
            拒绝
          </button>
        </span>
      </li>
    );
  }

  if (kind === "context") {
    return (
      <li className="text-[11px] text-muted">
        <span className="mr-1 rounded bg-gray-100 px-1">上下文</span>
        仓库 {data.repo} · 历史 {data.history_turns} 轮 · 记忆命中 {data.memory_hits} · 预算{" "}
        {data.budget?.used}/{data.budget?.total}
      </li>
    );
  }

  if (kind === "citation") {
    return (
      <li className="text-[11px] text-muted">
        <span className="mr-1.5 rounded-md bg-neutral-soft px-1.5 py-0.5 text-[10px]">引用</span>
        {data.doc_path} &gt; {data.heading_path}
      </li>
    );
  }

  if (kind === "error") {
    return (
      <li className="text-[11px] text-danger">
        <span className="mr-1 rounded bg-danger-soft px-1">错误</span>
        {data.message}
      </li>
    );
  }

  return null;
}

export default RunTrace;