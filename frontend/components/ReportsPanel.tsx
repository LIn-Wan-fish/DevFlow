"use client";

import { useEffect, useState } from "react";

import Markdown from "@/components/Markdown";
import { api } from "@/lib/api";

type Report = {
  id: number; period_key: string; trigger: string; path: string; summary: string;
  open_issues: number; merged_prs: number; failed_ci: number; generated_at: string;
};

type Scheduler = { enabled: boolean; check_seconds: number; days: number; current_period: string };

/**
 * 周报面板。
 *
 * 刻意把**调度配置**一并显示:周报是自动生成的,不写清楚「什么时候生成、多久检查一次」,
 * 用户看到一份凭空出现的报告只会困惑。所以这里如实展示 enabled / 周期 / 检查间隔。
 */
export default function ReportsPanel({ repoId }: { repoId: number }) {
  const [items, setItems] = useState<Report[]>([]);
  const [scheduler, setScheduler] = useState<Scheduler | null>(null);
  const [body, setBody] = useState<{ id: number; body: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const data = await api.reports(repoId);
      setItems(data.items);
      setScheduler(data.scheduler);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    void load();
  }, [repoId]);

  const generate = async () => {
    setBusy(true);
    try {
      const report = await api.generateReport(repoId);
      setBody(report);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (id: number) => {
    try {
      setBody(await api.report(id));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      {scheduler ? (
        <div className="rounded-lg border border-line bg-sunken px-2.5 py-2 text-[11px] leading-relaxed text-muted">
          自动周报:{scheduler.enabled ? "已开启" : "已关闭"} · 每{" "}
          {Math.round(scheduler.check_seconds / 60)} 分钟检查一次 · 统计窗口{" "}
          {scheduler.days} 天 · 当前周期 <code>{scheduler.current_period}</code>
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <span className="text-muted">共 {items.length} 份</span>
        <button
          className="rounded-lg border border-line bg-panel px-2.5 py-1 text-[11px] transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-50"
          disabled={busy}
          onClick={generate}
        >
          {busy ? "生成中…" : "立即生成"}
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-[11px] text-danger">
          {error}
        </div>
      ) : null}

      {items.map((item) => (
        <button
          key={item.id}
          className="rounded-xl border border-line bg-panel px-2.5 py-2 text-left shadow-soft transition-all hover:border-accent/40 hover:shadow-card"
          onClick={() => open(item.id)}
        >
          <div className="flex items-center justify-between">
            <span className="font-medium">{item.period_key}</span>
            <span className="text-[10px] text-muted">
              {item.trigger === "auto" ? "自动" : "手动"}
            </span>
          </div>
          <div className="text-[11px] text-muted">{item.summary}</div>
        </button>
      ))}

      {body ? (
        <div className="max-h-72 overflow-auto rounded-xl border border-line bg-sunken p-3">
          <Markdown>{body.body}</Markdown>
        </div>
      ) : null}
    </div>
  );
}