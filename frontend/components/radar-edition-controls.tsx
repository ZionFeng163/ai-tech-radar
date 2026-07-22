"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { RadarEdition } from "@/lib/types";

const POLL_INTERVAL_MS = 2_000;
const MAX_POLLS = 150;

export function RadarEditionControls({
  editions,
  selectedId,
}: {
  editions: RadarEdition[];
  selectedId?: string;
}) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "running" | "error">("idle");
  const completed = editions.filter((edition) => edition.status === "complete");

  function switchEdition(value: string) {
    if (!value) return;
    router.push(`/?edition=${encodeURIComponent(value)}`);
  }

  async function capture() {
    setState("running");
    try {
      const response = await fetch("/api/radar-editions", { method: "POST" });
      if (!response.ok) throw new Error("capture failed");
      const edition = (await response.json()) as RadarEdition;
      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
        const statusResponse = await fetch(`/api/radar-editions/${edition.id}`, {
          cache: "no-store",
        });
        if (!statusResponse.ok) throw new Error("status failed");
        const current = (await statusResponse.json()) as RadarEdition;
        if (current.status === "complete") {
          router.push(`/?edition=${encodeURIComponent(current.id)}`);
          router.refresh();
          setState("idle");
          return;
        }
        if (current.status === "failed") throw new Error("capture failed");
      }
      throw new Error("capture timed out");
    } catch {
      setState("error");
    }
  }

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
        {state === "running" ? "正在抓取并生成概览…" : "手动抓取新一期"}
      </button>
      {state === "error" ? <p>抓取失败，请查看服务日志后重试。</p> : null}
    </section>
  );
}

function formatCapturedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}
