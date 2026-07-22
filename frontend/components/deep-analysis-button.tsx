"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DeepAnalysisButton({ articleId }: { articleId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  async function generate() {
    setStatus("loading");
    try {
      const response = await fetch(`/api/articles/${encodeURIComponent(articleId)}/deep-analysis`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(`request failed: ${response.status}`);
      router.refresh();
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="deep-analysis-cta">
      <p className="section-index">ON DEMAND / DEEP DIVE</p>
      <h2>想继续看这项技术？</h2>
      <p>当前只展示快速概览。点击后才会调用 AI 阅读现有资料，生成核心创新、差异、场景和价值判断。</p>
      <button className="action-button" disabled={status === "loading"} onClick={generate}>
        {status === "loading" ? "正在生成深度分析…" : "生成深度分析"}
      </button>
      {status === "error" ? <p className="deep-analysis-error">生成失败，请稍后重试。</p> : null}
    </div>
  );
}
