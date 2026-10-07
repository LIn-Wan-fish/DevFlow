"use client";

import type { RecallHit, RecallTrace } from "@/lib/types";

const STAGES: { key: keyof RecallTrace; label: string; hint: string }[] = [
  { key: "chunks", label: "切分", hint: "融合后进入候选的片段" },
  { key: "vector_hits", label: "向量召回", hint: "语义近似" },
  { key: "keyword_hits", label: "关键词召回", hint: "精确命中标识符" },
  { key: "fused_reranked", label: "RRF 融合 + 重排", hint: "最终证据" },
];

/** 召回测试:四阶段并列,用于诊断检索到底坏在哪一步。 */
export function RecallStages({ trace }: { trace: RecallTrace }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {STAGES.map((stage) => {
        const hits = (trace?.[stage.key] as RecallHit[]) ?? [];
        return (
          <div
            key={String(stage.key)}
            className="flex flex-col overflow-hidden rounded-xl border border-line bg-panel shadow-soft"
          >
            <div className="flex items-baseline gap-2 border-b border-line bg-sunken px-3 py-2.5">
              <span className="text-[12px] font-semibold">{stage.label}</span>
              <span className="truncate text-[10px] text-muted">{stage.hint}</span>
              <span className="ml-auto shrink-0 rounded-md bg-panel px-1.5 py-0.5 text-[10px] tabular-nums text-muted">
                {hits.length}
              </span>
            </div>
            <ul className="flex-1 space-y-2 p-2.5">
              {hits.map((hit) => (
                <li
                  key={`${stage.key}-${hit.chunk_id}`}
                  className="rounded-lg border border-line bg-canvas p-2 text-[11px]"
                >
                  <div className="truncate font-medium">
                    {hit.doc_path}
                    {hit.heading_path ? (
                      <span className="text-muted"> &gt; {hit.heading_path}</span>
                    ) : null}
                  </div>
                  <div className="mt-1 line-clamp-2 leading-relaxed text-muted">{hit.preview}</div>
                  {typeof hit.score === "number" ? (
                    <div className="mt-1 text-[10px] tabular-nums text-muted">
                      score {hit.score}
                    </div>
                  ) : null}
                </li>
              ))}
              {!hits.length ? (
                <li className="rounded-lg border border-dashed border-line p-3 text-center text-[11px] text-muted">
                  无命中
                </li>
              ) : null}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

export default RecallStages;