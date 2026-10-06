import type {
  CiItem,
  Draft,
  EvalResult,
  Health,
  IssueGroupCounts,
  IssueItem,
  MemoryCandidate,
  MemoryEntry,
  PrItem,
  RecallTrace,
  Repo,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} 返回 ${response.status}`);
  }
  return (await response.json()) as T;
}

async function post<T>(
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string" ? payload.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export const api = {
  repos: () => get<Repo[]>("/api/repos"),
  health: (repoId: number) => get<Health>(`/api/repos/${repoId}/health`),
  issues: (repoId: number, params: { state?: string; assignee?: string; q?: string } = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) search.set(key, value);
    });
    const suffix = search.toString() ? `?${search.toString()}` : "";
    return get<{ items: IssueItem[]; groups: IssueGroupCounts; total: number }>(
      `/api/repos/${repoId}/issues${suffix}`,
    );
  },
  prs: (repoId: number) => get<{ items: PrItem[] }>(`/api/repos/${repoId}/prs`),
  ci: (repoId: number) => get<{ items: CiItem[] }>(`/api/repos/${repoId}/ci`),
  drafts: (status = "pending") => get<Draft[]>(`/api/drafts?status=${status}`),
  allDrafts: () => get<Draft[]>("/api/drafts"),
  // 角色走请求头:服务端只认头,不认查询参数 —— 否则授权等于没有
  confirmDraft: (id: number, role = "member") =>
    post<Draft>(`/api/drafts/${id}/confirm`, undefined, { "X-DevFlow-Role": role }),
  rejectDraft: (id: number, role = "member") =>
    post<Draft>(`/api/drafts/${id}/reject`, undefined, { "X-DevFlow-Role": role }),
  authMode: () =>
    get<{ enforced: boolean; mode: string; roles: string[]; default_role: string }>(
      "/api/auth/mode",
    ),
  audit: () => get<Record<string, any>[]>("/api/drafts/audit"),
  memory: (repoId: number) =>
    get<{ candidates: MemoryCandidate[]; entries: MemoryEntry[] }>(
      `/api/memory/candidates?repo_id=${repoId}`,
    ),
  approveMemory: (id: number, approvedBy = "member") =>
    post<MemoryEntry>(`/api/memory/candidates/${id}/approve`, { approved_by: approvedBy }),
  rejectMemory: (id: number) =>
    post<MemoryCandidate>(`/api/memory/candidates/${id}/reject`),
  recallTest: (repoId: number, query: string) =>
    post<RecallTrace>("/api/rag/recall-test", { repo_id: repoId, query }),
  // 不传 mode 就由服务端按 LLM_MODE 决定:写死 mock 会让真实模型的运行被贴上 mock 标签
  runEval: (mode?: string) => post<EvalResult>("/api/eval/run", mode ? { mode } : {}),
  evalRuns: () => get<Record<string, any>[]>("/api/eval/runs"),
  mcpTools: () => get<{ tools: { name: string }[] }>("/api/mcp/tools"),
};