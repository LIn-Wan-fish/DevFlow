"use client";

type Citation = { doc_path: string; heading_path: string; score?: number };

/** 引用与证据。每条结论都要能点回到具体文档位置。 */
export function EvidenceList({ citations }: { citations: Citation[] }) {
  if (!citations?.length) return null;
  return (
    <div className="mt-2 rounded border border-line bg-canvas p-2">
      <div className="mb-1 text-[11px] font-semibold text-muted">引用与证据</div>
      <ul className="space-y-1">
        {citations.map((citation, index) => (
          <li key={`${citation.doc_path}-${index}`} className="text-[11px]">
            <span className="mr-1 text-accent">#{index + 1}</span>
            <span className="font-medium">{citation.doc_path}</span>
            {citation.heading_path ? (
              <span className="text-muted"> &gt; {citation.heading_path}</span>
            ) : null}
            {typeof citation.score === "number" ? (
              <span className="ml-1 text-muted">({citation.score.toFixed(3)})</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default EvidenceList;