export type Repo = {
  id: number;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  is_github: boolean;
};

export type Health = {
  repo: string;
  open_issues: number;
  prs_pending_review: number;
  issues_resolved: number;
  issues_rejected: number;
  failed_ci: number;
  merged_prs: number;
};

export type IssueItem = {
  id: number;
  number: number;
  title: string;
  state: string;
  group: string;
  labels: string[];
  assignee: string | null;
  excerpt: string;
};

export type IssueGroupCounts = Record<string, number>;

export type PrFile = {
  path: string;
  additions: number;
  deletions: number;
  is_high_risk: boolean;
};

export type PrItem = {
  id: number;
  number: number;
  title: string;
  state: string;
  merged: boolean;
  head_ref: string;
  base_ref: string;
  files: PrFile[];
};

export type CiItem = {
  id: number;
  number: number;
  workflow: string;
  branch: string;
  conclusion: string;
  duration_seconds: number;
};

export type Draft = {
  id: number;
  action: string;
  target: string;
  preview: string;
  risk_level: string;
  status: string;
  requested_by_role: string;
};

export type MemoryCandidate = {
  id: number;
  content: string;
  confidence: number;
  status: string;
  run_id: number | null;
};

export type MemoryEntry = {
  id: number;
  content: string;
  approved_by: string;
  source_candidate_id: number | null;
};

/** SSE 事件 —— 后端 events.py 里的 EventKind 一一对应 */
export type SseEvent = {
  event: string;
  data: Record<string, any>;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  events?: SseEvent[];
  citations?: { doc_path: string; heading_path: string; score?: number }[];
  drafts?: Draft[];
  nextSteps?: string[];
  stopReason?: string;
  steps?: number;
  error?: string;
  streaming?: boolean;
  /** 流式增量缓冲:token 事件逐段累加;done 到达后清空并由 content 接管 */
  streamingText?: string;
  /** 模型**上报**的 token 用量;未上报就是 0,不用估算值冒充 */
  totalTokens?: number;
};

export type RecallTrace = {
  query: string;
  chunks: RecallHit[];
  vector_hits: RecallHit[];
  keyword_hits: RecallHit[];
  fused_reranked: RecallHit[];
};

export type RecallHit = {
  chunk_id: number;
  doc_path: string;
  heading_path: string;
  preview: string;
  token_count?: number;
  score?: number;
};

export type EvalCaseResult = {
  key: string;
  question: string;
  passed: boolean;
  rule_results: { rule: string; passed: boolean; detail: string }[];
  actual: Record<string, any>;
};

export type EvalResult = {
  eval_run_id: number;
  total: number;
  passed: number;
  failed: number;
  metrics: Record<string, string>;
  cases: EvalCaseResult[];
};