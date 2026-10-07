"use client";

import { useEffect, useRef, useState } from "react";

import Markdown from "@/components/Markdown";

/**
 * 逐字显示的流式文本。
 *
 * 模型一次会吐**好几个字**,前端直接追加就成了"一段一段"地跳 ——
 * 和各家 LLM 的逐字观感差很远。这里把"已经到达的文本"按帧慢慢露出来,
 * 视觉上就是逐字输出。**不改变数据本身,只改变显示节奏**。
 *
 * 落后越多追得越快:既保持逐字观感,又不会在大段落后时慢得离谱。
 */
export default function StreamingMarkdown({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const [shown, setShown] = useState(streaming ? "" : text);
  const revealed = useRef(streaming ? 0 : text.length);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (!streaming) {
      // 结束或中断时立刻补齐 —— 不能卡在半截,那会让人以为内容丢了
      revealed.current = text.length;
      setShown(text);
      return;
    }
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const remain = text.length - revealed.current;
      if (remain <= 0) return;
      revealed.current = Math.min(text.length, revealed.current + Math.max(1, Math.ceil(remain / 12)));
      setShown(text.slice(0, revealed.current));
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      alive = false;
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [text, streaming]);

  return <Markdown streaming={streaming}>{shown}</Markdown>;
}
