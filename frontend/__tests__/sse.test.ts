import { describe, expect, test } from "vitest";

import { parseSSEChunk } from "@/lib/sse";

describe("SSE 解析", () => {
  test("解析单个完整帧", () => {
    const { events, rest } = parseSSEChunk('event: tool_call\ndata: {"tool":"debug_ci"}\n\n');
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: "tool_call", data: { tool: "debug_ci" } });
    expect(rest).toBe("");
  });

  test("半帧被缓存到下次", () => {
    const first = parseSSEChunk('event: token\ndata: {"delta":"你');
    expect(first.events).toHaveLength(0);
    const second = parseSSEChunk(`${first.rest}"}\n\n`);
    expect(second.events[0].data.delta).toBe("你");
  });

  test("忽略心跳注释行", () => {
    const { events } = parseSSEChunk(': ping\n\nevent: done\ndata: {"run_id":1}\n\n');
    expect(events.map((event) => event.event)).toEqual(["done"]);
  });

  test("中文不被破坏", () => {
    const { events } = parseSSEChunk('event: token\ndata: {"delta":"失败"}\n\n');
    expect(events[0].data.delta).toBe("失败");
  });

  test("一次解析多个帧", () => {
    const { events } = parseSSEChunk(
      'event: plan\ndata: {"tasks":[]}\n\nevent: done\ndata: {"run_id":2}\n\n',
    );
    expect(events.map((event) => event.event)).toEqual(["plan", "done"]);
  });
});