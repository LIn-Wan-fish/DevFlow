"use client";

import type { Repo } from "@/lib/types";

export type SessionNode = { id: number; title: string; age: string };

type Props = {
  repos: Repo[];
  activeRepoId: number;
  sessions: SessionNode[];
  activeSession: string;
  onSelectRepo: (repoId: number) => void;
  onSelectSession: (title: string) => void;
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
      <div className="flex items-center gap-2 px-3 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-ink text-[11px] font-bold text-white">
          DF
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold">DevFlow AI</div>
          <div className="text-[10px] text-muted">研发团队 PR / Issue 智能协作</div>
        </div>
      </div>

      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-[11px] font-semibold tracking-wide text-muted">PROJECTS</span>
        <button
          onClick={onAddProject}
          className="text-[11px] text-muted hover:text-ink"
          type="button"
        >
          项目
        </button>
      </div>
      <div className="px-3 pb-2">
        <button
          type="button"
          onClick={onAddProject}
          className="w-full rounded border border-dashed border-line px-2 py-1 text-[11px] text-muted hover:border-accent hover:text-accent"
        >
          + 添加项目
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2">
        {repos.map((repo) => (
          <div key={repo.id} className="mb-1">
            <button
              type="button"
              onClick={() => onSelectRepo(repo.id)}
              className={`flex w-full items-center gap-1 rounded px-2 py-1 text-left text-[12px] ${
                repo.id === activeRepoId ? "bg-canvas font-medium" : "hover:bg-canvas"
              }`}
            >
              <span className="text-muted">▾</span>
              <span className="truncate">{repo.name}</span>
            </button>
            <ul className="ml-4 mt-0.5 space-y-0.5">
              {sessions.map((session) => (
                <li key={session.id}>
                  <button
                    type="button"
                    onClick={() => onSelectSession(session.title)}
                    className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-[12px] ${
                      session.title === activeSession
                        ? "bg-canvas text-accent"
                        : "text-muted hover:bg-canvas"
                    }`}
                  >
                    <span className="truncate">{session.title}</span>
                    <span className="ml-2 shrink-0 text-[10px] text-muted">{session.age}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex items-center gap-2 border-t border-line p-2">
        <button
          type="button"
          onClick={onRefresh}
          className="flex-1 rounded border border-line px-2 py-1.5 text-[12px] hover:border-accent hover:text-accent"
        >
          刷新当前项目
        </button>
        {footer}
      </div>
    </aside>
  );
}

export default ProjectSidebar;