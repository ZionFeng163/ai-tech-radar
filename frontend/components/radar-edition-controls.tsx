"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type { CleanupReport, RadarEdition } from "@/lib/types";

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
  const [keepEditions, setKeepEditions] = useState(10);
  const [cleanupState, setCleanupState] = useState<
    "idle" | "loading" | "ready" | "done" | "error"
  >("idle");
  const [cleanupReport, setCleanupReport] = useState<CleanupReport | null>(null);
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

  async function previewCleanup() {
    setCleanupState("loading");
    try {
      const response = await fetch(
        `/api/maintenance/cleanup?keep_editions=${keepEditions}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("preview failed");
      setCleanupReport((await response.json()) as CleanupReport);
      setCleanupState("ready");
    } catch {
      setCleanupState("error");
    }
  }

  async function runCleanup() {
    if (!cleanupReport || cleanupReport.blocked) return;
    const confirmed = window.confirm(
      `将保留最近 ${keepEditions} 期，并永久删除预览中的旧数据。确定继续吗？`,
    );
    if (!confirmed) return;
    setCleanupState("loading");
    try {
      const response = await fetch(
        `/api/maintenance/cleanup?keep_editions=${keepEditions}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("cleanup failed");
      setCleanupReport((await response.json()) as CleanupReport);
      setCleanupState("done");
      router.push("/");
      router.refresh();
    } catch {
      setCleanupState("error");
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
      <details className="cleanup-controls">
        <summary>数据清理</summary>
        <div className="cleanup-form">
          <label>
            <span>保留最近</span>
            <select
              value={keepEditions}
              onChange={(event) => {
                setKeepEditions(Number(event.target.value));
                setCleanupState("idle");
                setCleanupReport(null);
              }}
            >
              <option value={5}>5 期</option>
              <option value={10}>10 期</option>
              <option value={20}>20 期</option>
            </select>
          </label>
          <button
            className="secondary-button"
            disabled={state === "running" || cleanupState === "loading"}
            onClick={previewCleanup}
          >
            {cleanupState === "loading" ? "计算中…" : "预览清理"}
          </button>
        </div>
        {cleanupReport ? (
          <div className="cleanup-preview" role="status">
            <strong>{cleanupState === "done" ? "清理完成" : "预计清理"}</strong>
            <span>{cleanupReport.editions} 期</span>
            <span>{cleanupReport.articles} 篇文章</span>
            <span>{cleanupReport.raw_items} 条原始记录</span>
            <span>{cleanupReport.fetch_runs + cleanupReport.analysis_runs} 条运行日志</span>
            {cleanupReport.blocked ? (
              <p>当前有抓取或分析任务运行中，完成后才能清理。</p>
            ) : cleanupState === "ready" ? (
              <button className="danger-button" onClick={runCleanup}>确认清理</button>
            ) : null}
          </div>
        ) : null}
        {cleanupState === "error" ? <p>清理预览失败，请稍后重试。</p> : null}
      </details>
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
