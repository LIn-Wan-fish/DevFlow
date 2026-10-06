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
          <div key={String(stage.key)} className="rounded border border-line bg-panel">
            <div className="flex items-baseline gap-2 border-b border-line px-2 py-1.5">
              <span className="text-[12px] font-semibold">{stage.label}</span>
              <span className="text-[10px] text-muted">{stage.hint}</span>
              <span className="ml-auto text-[11px] text-muted">{hits.length}</span>
            </div>
            <ul className="space-y-1 p-2">
              {hits.map((hit) => (
                <li key={`${stage.key}-${hit.chunk_id}`} className="text-[11px]">
                  <div className="font-medium">
                    {hit.doc_path}
                    {hit.heading_path ? (
                      <span className="text-muted"> &gt; {hit.heading_path}</span>
                    ) : null}
                  </div>
                  <div className="line-clamp-2 text-muted">{hit.preview}</div>
                  {typeof hit.score === "number" ? (
                    <div className="text-[10px] text-muted">score {hit.score}</div>
                  ) : null}
                </li>
              ))}
              {!hits.length ? <li className="text-[11px] text-muted">无命中</li> : null}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

export default RecallStages;