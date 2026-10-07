import { API_BASE, getRoleToken } from "./api";
import type { SseEvent } from "./types";

export type ParsedChunk = {
  events: SseEvent[];
  rest: string;
  done: boolean;
};

/**
 * 按帧解析 SSE。
 *
 * 两个容易踩的坑:
 * 1. 一个网络 chunk 里可能是半帧,必须把残帧返回给调用方缓存到下次;
 * 2. 多字节字符(中文)可能被切在两个 chunk 之间,所以解码必须用
 *    TextDecoder({stream: true}),不能对 Uint8Array 直接 toString。
 */
export function parseSSEChunk(buffer: string): ParsedChunk {
  const events: SseEvent[] = [];
  let rest = buffer;
  let done = false;

  while (true) {
    const boundary = rest.indexOf("\n\n");
    if (boundary === -1) break;
    const frame = rest.slice(0, boundary);
    rest = rest.slice(boundary + 2);

    let eventName = "message";
    const dataLines: string[] = [];
    for (const rawLine of frame.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      if (line.startsWith(":")) continue; // 心跳注释行
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (!dataLines.length) continue;

    const payload = dataLines.join("\n");
    if (payload === "[DONE]") {
      done = true;
      continue;
    }
    try {
      events.push({ event: eventName, data: JSON.parse(payload) });
    } catch {
      events.push({ event: eventName, data: { raw: payload } });
    }
  }

  return { events, rest, done };
}

export type StreamHandlers = {
  onEvent: (event: SseEvent) => void;
  onError?: (message: string) => void;
  onFinish?: () => void;
};

export async function streamChat(
  payload: { session_id: string; repo_id: number; message: string },
  handlers: StreamHandlers,
  signal?: AbortSignal,
  role = "member",
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: "POST",
      // 角色走请求头,不放请求体:服务端只从头上解析角色
      // 令牌模式下角色名无效,必须带令牌;没配令牌时退回演示模式(角色名可被服务端读)
      headers: {
        "Content-Type": "application/json",
        "X-DevFlow-Role": role,
        ...(getRoleToken() ? { "X-DevFlow-Role-Token": getRoleToken() } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    handlers.onError?.(`无法连接后端:${(error as Error).message}`);
    handlers.onFinish?.();
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError?.(`对话接口返回 ${response.status}`);
    handlers.onFinish?.();
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSSEChunk(buffer);
      buffer = rest;
      for (const event of events) {
        handlers.onEvent(event);
        if (event.event === "error") {
          handlers.onError?.(String(event.data?.message ?? "未知错误"));
        }
      }
    }
    // 冲刷解码器里可能残留的最后一个多字节字符
    buffer += decoder.decode();
    const tail = parseSSEChunk(buffer);
    tail.events.forEach(handlers.onEvent);
  } catch (error) {
    if ((error as Error).name !== "AbortError") {
      handlers.onError?.((error as Error).message);
    }
  } finally {
    handlers.onFinish?.();
  }
}