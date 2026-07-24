"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type { RadarEdition } from "@/lib/types";

const POLL_INTERVAL_MS = 2_000;
const MAX_POLLS = 300;

export function RadarEditionControls({
  editions,
  selectedId,
}: {
  editions: RadarEdition[];
  selectedId?: string;
}) {
  const router = useRouter();
  const runningEdition = editions.find((edition) => edition.status === "running");
  const [state, setState] = useState<"idle" | "running" | "error">(
    runningEdition ? "running" : "idle",
  );
  const [activeEdition, setActiveEdition] = useState<RadarEdition | null>(
    runningEdition ?? null,
  );
  const completed = editions.filter((edition) => edition.status === "complete");

  function switchEdition(value: string) {
    if (!value) return;
    router.push(`/?edition=${encodeURIComponent(value)}`);
  }

  const pollEdition = useCallback(async (editionId: string) => {
      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
        const statusResponse = await fetch(`/api/radar-editions/${editionId}`, {
          cache: "no-store",
        });
        if (!statusResponse.ok) throw new Error("status failed");
        const current = (await statusResponse.json()) as RadarEdition;
        setActiveEdition(current);
        if (current.status === "complete") {
          router.push(`/?edition=${encodeURIComponent(current.id)}`);
          router.refresh();
          setState("idle");
          return;
        }
        if (current.status === "failed") throw new Error("capture failed");
      }
      throw new Error("capture timed out");
  }, [router]);

  useEffect(() => {
    if (!runningEdition) return;
    setState("running");
    setActiveEdition(runningEdition);
    void pollEdition(runningEdition.id).catch(() => setState("error"));
  }, [pollEdition, runningEdition]);

  async function capture() {
    setState("running");
    try {
      const response = await fetch("/api/radar-editions", { method: "POST" });
      if (!response.ok) throw new Error("capture failed");
      const edition = (await response.json()) as RadarEdition;
      setActiveEdition(edition);
      await pollEdition(edition.id);
    } catch {
      setState("error");
    }
  }

  const progress = activeEdition?.progress;
  const progressPercent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.completed / progress.total) * 100))
      : 0;

  return (
    <section className="edition-controls shell" aria-label="雷达抓取批次">
      <label>
        <span>抓取日期</span>
        <select value={selectedId ?? ""} onChange={(event) => switchEdition(event.target.value)}>
          {!completed.length ? <option value="">暂无抓取记录</option> : null}
          {completed.map((edition) => (
            <option value={edition.id} key={edition.id}>
              {formatCapturedAt(edition.captured_at)}
            </option>
          ))}
        </select>
      </label>
      <button className="action-button" disabled={state === "running"} onClick={capture}>
        {state === "running" ? "抓取进行中…" : "手动抓取新一期"}
      </button>
      {state === "running" && progress ? (
        <div className="edition-progress" role="status" aria-live="polite">
          <div>
            <strong>{stageLabel(progress.stage)}</strong>
            <span>{progress.message}</span>
            {progress.total > 0 ? (
              <small>{progress.completed}/{progress.total} · {progressPercent}%</small>
            ) : null}
          </div>
          <progress max={100} value={progressPercent}>{progressPercent}%</progress>
        </div>
      ) : null}
      {state === "error" ? <p>抓取失败，请查看服务日志后重试。</p> : null}
    </section>
  );
}

function stageLabel(stage: RadarEdition["progress"]["stage"]): string {
  const labels = {
    queued: "等待开始",
    collecting: "抓取 API",
    normalizing: "整理数据",
    analyzing: "生成概览",
    complete: "已完成",
    failed: "失败",
  };
  return labels[stage];
}

function formatCapturedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}
