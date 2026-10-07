"use client";

import type { Repo } from "@/lib/types";

export type SessionNode = { id: number; title: string; age: string };

type Props = {
  repos: Repo[];
  activeRepoId: number;
  sessions: SessionNode[];
  /**
   * 当前选中的会话,**形如 `仓库id:会话id`**。
   *
   * 原先这里存的是会话**标题**,而不同项目下都有叫「默认会话」的会话 ——
   * 于是点一个会把所有同名的都点亮。标题是给人看的,不该拿来当身份。
   */
  activeSession: string;
  onSelectRepo: (repoId: number) => void;
  onSelectSession: (sessionId: number) => void;
  onRefresh: () => void;
  onAddProject: () => void;
  /** 由拖拽决定;不传则用默认宽度 */
  width?: number;
  /** 底部的额外内容(主题切换等) */
  footer?: React.ReactNode;
};

/** 左栏:项目/会话树(对应 img_01 左侧)。 */
export function ProjectSidebar({
  repos,
  activeRepoId,
  sessions,
  activeSession,
  onSelectRepo,
  onSelectSession,
  onRefresh,
  onAddProject,
  width = 248,
  footer,
}: Props) {
  return (
    <aside style={{ width }} className="flex h-full shrink-0 flex-col border-r border-line bg-panel">
      <div className="flex items-center gap-2.5 px-3 pb-1 pt-3.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-[11px] font-semibold tracking-tight text-white shadow-soft">
          DF
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[14px] font-semibold tracking-tight">DevFlow AI</div>
          <div className="truncate text-[10px] text-muted">研发团队 PR / Issue 智能协作</div>
        </div>
      </div>

      <div className="flex items-center justify-between px-3 pb-1.5 pt-3">
        <span className="text-[10px] font-semibold tracking-[0.08em] text-muted">PROJECTS</span>
        <button
          onClick={onAddProject}
          className="text-[11px] text-muted transition-colors hover:text-accent"
          type="button"
        >
          项目
        </button>
      </div>
      <div className="px-3 pb-2">
        <button
          type="button"
          onClick={onAddProject}
          className="w-full rounded-lg border border-dashed border-line px-2 py-1.5 text-[11px] text-muted transition-colors hover:border-accent/60 hover:bg-accent-soft hover:text-accent"
        >
          + 添加项目
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {repos.map((repo) => (
          <div key={repo.id} className="mb-1.5">
            <button
              type="button"
              onClick={() => onSelectRepo(repo.id)}
              className={`flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-[12px] transition-colors ${
                repo.id === activeRepoId
                  ? "bg-accent-soft font-medium text-ink"
                  : "text-muted hover:bg-hover hover:text-ink"
              }`}
            >
              <span className="text-[9px] text-muted">▾</span>
              <span className="truncate">{repo.name}</span>
            </button>
            {/* 竖线做出树的层级,比单纯缩进更好读 */}
            <ul className="ml-3 mt-1 space-y-0.5 border-l border-line pl-2">
              {sessions.map((session) => (
                <li key={session.id}>
                  <button
                    type="button"
                    onClick={() => onSelectSession(session.id)}
                    className={`flex w-full items-center justify-between rounded-lg px-2 py-1 text-left text-[12px] transition-colors ${
                      `${repo.id}:${session.id}` === activeSession
                        ? "bg-accent-soft font-medium text-accent"
                        : "text-muted hover:bg-hover hover:text-ink"
                    }`}
                  >
                    <span className="truncate">{session.title}</span>
                    <span className="ml-2 shrink-0 text-[10px] tabular-nums text-muted">
                      {session.age}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex items-center gap-2 border-t border-line p-2.5">
        <button
          type="button"
          onClick={onRefresh}
          className="flex-1 rounded-lg border border-line px-2 py-1.5 text-[12px] text-muted transition-colors hover:border-accent/50 hover:text-accent"
        >
          刷新当前项目
        </button>
        {footer}
      </div>
    </aside>
  );
}

export default ProjectSidebar;