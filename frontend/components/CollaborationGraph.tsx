"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";

export type Finding = {
  id: number; author: string; topic: string; conclusion: string;
  confidence: number; status: string; references: number[];
  supersedes_id: number | null; created_at: string | null;
};

type Payload = {
  run_id: number; findings: Finding[]; active_finding_ids: number[];
  edges: { from: number; to: number }[];
  conflicts: { topic: string; authors: string[]; conclusions: string[] }[];
  authors: string[];
};

const NODE_W = 168;
const NODE_H = 46;
const COL_GAP = 74;
const ROW_GAP = 16;

/**
 * 分层:没有引用的在第 0 层,其余的层号 = 被引用者的最大层号 + 1。
 *
 * **必须先算层再定位**,不能按数据库顺序平铺 —— 那样画出来是一团线,
 * 看不出"谁基于谁"。这也是分支浏览器存在的意义:把协作的顺序变成可读的形状。
 */
export function layout(findings: Finding[]): Map<number, { col: number; row: number }> {
  const byId = new Map(findings.map((f) => [f.id, f]));
  const depth = new Map<number, number>();
  const resolve = (id: number, seen: Set<number>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0;            // 环:理论上不该有,真出现了也不能卡死
    seen.add(id);
    const refs = (byId.get(id)?.references ?? []).filter((r) => byId.has(r));
    const value = refs.length ? 1 + Math.max(...refs.map((r) => resolve(r, seen))) : 0;
    depth.set(id, value);
    return value;
  };
  findings.forEach((f) => resolve(f.id, new Set()));

  const used = new Map<number, number>();
  const out = new Map<number, { col: number; row: number }>();
  [...findings]
    .sort((a, b) => (depth.get(a.id)! - depth.get(b.id)!) || a.id - b.id)
    .forEach((f) => {
      const col = depth.get(f.id)!;
      const row = used.get(col) ?? 0;
      used.set(col, row + 1);
      out.set(f.id, { col, row });
    });
  return out;
}

export default function CollaborationGraph({ runId }: { runId: number | null }) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (runId === null) return;
    api.findings(runId).then(setData).catch((e) => setError((e as Error).message));
  }, [runId]);

  const view = useMemo(() => {
    if (!data || data.findings.length === 0) return null;
    const pos = layout(data.findings);
    const cols = Math.max(...[...pos.values()].map((p) => p.col)) + 1;
    const rows = Math.max(...[...pos.values()].map((p) => p.row)) + 1;
    const at = (id: number) => {
      const p = pos.get(id)!;
      return { x: p.col * (NODE_W + COL_GAP), y: p.row * (NODE_H + ROW_GAP) };
    };
    return { pos, at, width: cols * NODE_W + (cols - 1) * COL_GAP,
             height: rows * NODE_H + (rows - 1) * ROW_GAP };
  }, [data]);

  if (runId === null) return null;
  if (error) return <div className="mt-2 text-[11px] text-danger">协作图加载失败:{error}</div>;
  if (!data) return <div className="mt-2 text-[11px] text-muted">正在读取共享发现板…</div>;
  if (!view) return <div className="mt-2 text-[11px] text-muted">本次运行没有产生发现。</div>;

  const dead = new Set(data.findings.map((f) => f.id).filter((id) => !data.active_finding_ids.includes(id)));
  const conflicted = new Set(data.conflicts.flatMap((c) => c.topic));

  return (
    <div className="mt-2 rounded border border-line bg-panel p-2">
      <div className="mb-1.5 flex items-center justify-between text-[11px]">
        <span className="font-medium">协作图</span>
        <span className="text-muted">
          {data.findings.length} 条发现 · {data.edges.length} 条引用 · {data.authors.length} 个 Agent
        </span>
      </div>

      <div className="overflow-x-auto">
        <svg width={view.width + 8} height={view.height + 8} className="block">
          {data.edges.map((e, i) => {
            const a = view.at(e.to);
            const b = view.at(e.from);
            if (!a || !b) return null;
            const x1 = a.x + NODE_W;
            const y1 = a.y + NODE_H / 2;
            const x2 = b.x;
            const y2 = b.y + NODE_H / 2;
            const mid = (x1 + x2) / 2;
            return (
              <path key={i} d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`}
                    fill="none" stroke="currentColor" strokeWidth={1.2}
                    className="text-line" markerEnd="url(#arrow)" />
            );
          })}
          <defs>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill="currentColor" className="text-line" />
            </marker>
          </defs>
          {data.findings.map((f) => {
            const p = view.at(f.id);
            const faded = dead.has(f.id);
            const hot = conflicted.has(f.topic);
            return (
              <g key={f.id} transform={`translate(${p.x},${p.y})`} opacity={faded ? 0.45 : 1}>
                <rect width={NODE_W} height={NODE_H} rx={5}
                      className={hot ? "fill-warn-soft stroke-warn" : "fill-canvas stroke-line"}
                      strokeWidth={1} />
                <text x={8} y={16} className="fill-ink text-[10px] font-medium">
                  {f.author}
                </text>
                <text x={8} y={30} className="fill-muted text-[9px]">
                  {f.topic.length > 22 ? f.topic.slice(0, 22) + "…" : f.topic}
                </text>
                <text x={8} y={41} className="fill-muted text-[8px]">
                  {`#${f.id} 置信 ${f.confidence}`}{faded ? " · 已被取代" : ""}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {data.conflicts.length > 0 ? (
        <div className="mt-2 rounded bg-warn-soft px-2 py-1 text-[11px] text-warn">
          {data.conflicts.map((c) => (
            <div key={c.topic}>
              分歧「{c.topic}」:{c.authors.join(" vs ")} —— 结论不一致,需要人工判断
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
