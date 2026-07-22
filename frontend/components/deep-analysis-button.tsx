"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

interface AnalysisJobStatus {
  status: "idle" | "queued" | "running" | "complete" | "failed";
}

const POLL_INTERVAL_MS = 1_200;
const MAX_POLLS = 75;

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
      const started = (await response.json()) as AnalysisJobStatus;
      if (started.status === "complete") {
        router.refresh();
        return;
      }
      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
        const statusResponse = await fetch(
          `/api/articles/${encodeURIComponent(articleId)}/analysis-status`,
          { cache: "no-store" },
        );
        if (!statusResponse.ok) throw new Error(`status failed: ${statusResponse.status}`);
        const job = (await statusResponse.json()) as AnalysisJobStatus;
        if (job.status === "complete") {
          router.refresh();
          return;
        }
        if (job.status === "failed") throw new Error("analysis failed");
      }
      throw new Error("analysis timed out");
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
        {status === "loading" ? "后台生成中，可继续浏览…" : "生成深度分析"}
      </button>
      {status === "error" ? <p className="deep-analysis-error">生成失败，请稍后重试。</p> : null}
    </div>
  );
}
