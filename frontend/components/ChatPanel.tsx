"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { streamChat } from "@/lib/sse";
import type { ChatMessage, SseEvent } from "@/lib/types";
import DraftCard from "./DraftCard";
import EvidenceList from "./EvidenceList";
import Markdown from "./Markdown";
import RunTrace from "./RunTrace";

const QUICK_PROMPTS = [
  "Issue #3: Feature: 增加桌面化能力 应该分给谁?",
  "分析 Issue #3 的优先级和复杂度",
  "给 Issue #3 写一条查询评论草稿",
];

type Props = {
  repoId: number;
  sessionId: string;
  role: string;
  quoted: string;
  onQuotedConsumed: () => void;
  onRunFinished: () => void;
};

/** 中栏:对话流 + 内嵌执行轨迹。 */
export function ChatPanel({
  repoId,
  sessionId,
  role,
  quoted,
  onQuotedConsumed,
  onRunFinished,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (quoted) {
      setInput((current) => `${quoted}${current}`);
      onQuotedConsumed();
    }
  }, [quoted, onQuotedConsumed]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || streaming) return;

    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: question,
    };
    const assistantId = `a-${Date.now()}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      events: [],
      citations: [],
      drafts: [],
      streaming: true,
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setInput("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const patch = (updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((current) =>
        current.map((message) => (message.id === assistantId ? updater(message) : message)),
      );
    };

    await streamChat(
      { session_id: sessionId, repo_id: repoId, message: question },
      {
        onEvent: (event: SseEvent) => {
          patch((message) => {
            // token 增量**不进事件列表**:一次回答可能有几百个增量帧,
            // 塞进去只会让轨迹数组和重渲染成本线性膨胀,
            // 而它唯一的作用就是拼出预览文本(轨迹组件本来也把它过滤掉了)。
            const next: ChatMessage = event.event === "token"
              ? { ...message }
              : { ...message, events: [...(message.events ?? []), event] };
            if (event.event === "citation") {
              next.citations = [...(message.citations ?? []), event.data as any];
            }
            if (event.event === "draft") {
              next.drafts = [
                ...(message.drafts ?? []),
                {
                  id: event.data.draft_id,
                  action: event.data.action,
                  target: event.data.target,
                  preview: event.data.preview ?? "",
                  risk_level: event.data.risk_level ?? "low",
                  status: event.data.status ?? "pending",
                  requested_by_role: role,
                },
              ];
            }
            if (event.event === "token") {
              // 增量文本:真实模型生成一段结论要几十秒,逐字显示比干等强得多。
              // done 到达时用权威答案覆盖,所以这里即便多显示了一点也不会残留。
              next.streamingText = (message.streamingText ?? "") + String(event.data.delta ?? "");
            }
            if (event.event === "done") {
              next.content = String(event.data.answer ?? "");
              next.stopReason = String(event.data.stop_reason ?? "");
              next.steps = Number(event.data.steps ?? 0);
              next.nextSteps = event.data.next_steps ?? [];
              next.totalTokens = Number(event.data.total_tokens ?? 0);
              // 权威答案已到,清掉增量缓冲
              next.streamingText = "";
            }
            if (event.event === "error") {
              next.error = String(event.data.message ?? "未知错误");
            }
            return next;
          });
        },
        onError: (message) => patch((current) => ({ ...current, error: message })),
        onFinish: () => {
          patch((current) => ({ ...current, streaming: false }));
          setStreaming(false);
          abortRef.current = null;
          onRunFinished();
        },
      },
      controller.signal,
      role,
    );
  };

  const confirmDraft = async (id: number) => {
    try {
      const updated = await api.confirmDraft(id, role);
      setMessages((current) =>
        current.map((message) => ({
          ...message,
          drafts: (message.drafts ?? []).map((draft) =>
            draft.id === id ? { ...draft, status: updated.status } : draft,
          ),
        })),
      );
    } catch (error) {
      window.alert(`确认失败:${(error as Error).message}`);
    }
  };

  const rejectDraft = async (id: number) => {
    try {
      const updated = await api.rejectDraft(id, role);
      setMessages((current) =>
        current.map((message) => ({
          ...message,
          drafts: (message.drafts ?? []).map((draft) =>
            draft.id === id ? { ...draft, status: updated.status } : draft,
          ),
        })),
      );
    } catch (error) {
      window.alert(`拒绝失败:${(error as Error).message}`);
    }
  };

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-canvas">
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <p className="mb-4 text-[12px] leading-relaxed text-muted">
          已切换到仓库 · 会话:{sessionId}。你可以直接问我 Issue、PR、CI 或周报相关问题。
        </p>

        {messages.map((message) => (
          <div key={message.id} className="mb-4 animate-fade-in">
            {message.role === "user" ? (
              <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[12px] leading-relaxed text-white shadow-soft">
                {message.content}
              </div>
            ) : (
              <div className="max-w-[95%] rounded-2xl border border-line bg-panel p-3 shadow-soft">
                {message.content || message.streamingText ? (
                  <div className="text-[12px] leading-relaxed">
                    {/* 模型输出的是 markdown,按纯文本直出会看到一堆 ** 和 | 符号。
                        流式期间也会渲染 —— 半截的代码围栏由组件内部兜底。 */}
                    <Markdown streaming={message.streaming && !message.content}>
                      {message.content || message.streamingText || ""}
                    </Markdown>
                    {message.streaming && !message.content ? (
                      <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse rounded-full bg-accent align-text-bottom" />
                    ) : null}
                  </div>
                ) : message.streaming ? (
                  <div className="flex items-center gap-1.5 text-[12px] text-muted">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                    正在取证与分析…
                  </div>
                ) : null}

                <RunTrace
                  events={message.events ?? []}
                  onConfirmDraft={confirmDraft}
                  onRejectDraft={rejectDraft}
                />
                <EvidenceList citations={message.citations ?? []} />

                {(message.drafts ?? []).map((draft) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    onConfirm={confirmDraft}
                    onReject={rejectDraft}
                  />
                ))}

                {message.error ? (
                  <div className="mt-2 rounded-lg border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-[11px] text-danger">
                    {message.error}
                  </div>
                ) : null}

                {message.stopReason && message.stopReason !== "completed" ? (
                  <div className="mt-1.5 text-[10px] text-warn">
                    停止原因:{message.stopReason}(已执行 {message.steps} 步)
                    {message.stopReason === "cancelled" ? "(已中断,后端不会再继续调用模型)" : ""}
                  </div>
                ) : null}

                {message.totalTokens ? (
                  <div className="mt-1 text-[10px] text-muted">
                    本次消耗 {message.totalTokens} tokens(模型上报)
                  </div>
                ) : null}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-line bg-panel px-4 py-3">
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              disabled={streaming}
              onClick={() => send(prompt)}
              className="rounded-full border border-line bg-canvas px-2.5 py-1 text-[11px] text-muted transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent disabled:opacity-40"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* 输入框做成一张「卡片」,边框和焦点态都挂在外层 —— 内部控件保持无边框 */}
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-canvas p-2 shadow-soft transition-colors focus-within:border-accent/50 focus-within:ring-2 focus-within:ring-accent/15">
          <textarea
            value={input}
            rows={2}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(input);
              }
            }}
            placeholder="输入消息,问问当前代码仓…"
            disabled={streaming}
            className="flex-1 resize-none bg-transparent px-2 py-1.5 text-[12px] leading-relaxed outline-none placeholder:text-muted/70 focus-visible:outline-none disabled:opacity-60"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="shrink-0 rounded-xl border border-line bg-panel px-3.5 py-2 text-[12px] text-muted transition-colors hover:border-accent/50 hover:text-accent"
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void send(input)}
              disabled={!input.trim()}
              className="shrink-0 rounded-xl bg-accent px-4 py-2 text-[12px] font-medium text-white shadow-soft transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              发送
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

export default ChatPanel;