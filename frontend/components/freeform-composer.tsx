"use client";

import { useState } from "react";

import type { ComposerMode, ComposerResponse } from "@/lib/types";

export function FreeformComposer() {
  const [mode, setMode] = useState<ComposerMode>("idea");
  const [fragments, setFragments] = useState("");
  const [paperUrl, setPaperUrl] = useState("");
  const [emphasis, setEmphasis] = useState("");
  const [draft, setDraft] = useState("");
  const [source, setSource] = useState<ComposerResponse["source"]>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  function switchMode(next: ComposerMode) {
    setMode(next);
    setDraft("");
    setSource(null);
    setError("");
  }

  async function generate() {
    setWorking(true);
    setError("");
    setCopied(false);
    try {
      const payload = mode === "idea"
        ? { fragments }
        : { url: paperUrl, emphasis };
      const response = await fetch(`/api/composer/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as ComposerResponse | { detail?: string };
      if (!response.ok || !("draft" in result)) {
        throw new Error("detail" in result && result.detail ? result.detail : "生成失败，请稍后重试");
      }
      setDraft(result.draft);
      setSource(result.source);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成失败，请稍后重试");
    } finally {
      setWorking(false);
    }
  }

  async function copyDraft() {
    await navigator.clipboard.writeText(draft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  const canGenerate = mode === "idea" ? fragments.trim().length >= 5 : paperUrl.trim().length >= 8;

  return (
    <div className="freeform-composer">
      <div className="composer-mode-picker" role="tablist" aria-label="写作方式">
        <button
          className={mode === "idea" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={mode === "idea"}
          onClick={() => switchMode("idea")}
        >
          <span>01</span>
          <strong>整理碎片想法</strong>
          <small>你提供判断，模型只负责把话说完整</small>
        </button>
        <button
          className={mode === "paper" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={mode === "paper"}
          onClick={() => switchMode("paper")}
        >
          <span>02</span>
          <strong>从论文链接写短帖</strong>
          <small>读取 arXiv 摘要，提炼机制、数字和判断</small>
        </button>
      </div>

      <section className="composer-input-panel">
        <p className="section-index">INPUT / RAW MATERIAL</p>
        {mode === "idea" ? (
          <label>
            <span>把想到的东西原样贴进来</span>
            <textarea
              value={fragments}
              onChange={(event) => setFragments(event.target.value)}
              placeholder="例如：AI 编程之后代码写得更快了，但 review、理解和维护可能反而更贵。速度不是工程效率……"
            />
            <small>不需要完整句子，也不需要先整理立场。不会替你编造经历和外部事实。</small>
          </label>
        ) : (
          <div className="paper-compose-fields">
            <label>
              <span>arXiv 论文链接</span>
              <input
                type="url"
                value={paperUrl}
                onChange={(event) => setPaperUrl(event.target.value)}
                placeholder="https://arxiv.org/abs/2607.08662"
              />
              <small>目前支持 arxiv.org/abs、arxiv.org/pdf 或 arXiv 编号。</small>
            </label>
            <label>
              <span>可选：你特别想强调什么</span>
              <textarea
                value={emphasis}
                onChange={(event) => setEmphasis(event.target.value)}
                placeholder="例如：我更关心它为什么不能提前固定任务分工。没有就留空。"
              />
            </label>
          </div>
        )}
        <button className="action-button composer-generate" type="button" disabled={!canGenerate || working} onClick={generate}>
          {working
            ? mode === "idea" ? "正在整理你的想法…" : "正在读取论文并写作…"
            : mode === "idea" ? "扩写成短推文" : "读取论文并生成短帖"}
        </button>
        {error ? <p className="studio-error" role="alert">{error}</p> : null}
      </section>

      {draft ? (
        <section className="composer-output-panel">
          <div className="composer-output-heading">
            <div>
              <p className="section-index">OUTPUT / EDITABLE DRAFT</p>
              <h2>第一版</h2>
            </div>
            <span>{draft.length} 字符</span>
          </div>
          {source ? (
            <div className="composer-paper-source">
              <strong>{source.title}</strong>
              <span>arXiv:{source.arxiv_id} · {source.authors.slice(0, 3).join("、")}</span>
            </div>
          ) : null}
          <textarea className="composer-draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
          <div className="studio-actions">
            <button className="secondary-button" type="button" onClick={copyDraft}>
              {copied ? "已复制" : "复制正文"}
            </button>
            <button className="action-button" type="button" disabled={working} onClick={generate}>
              {working ? "正在重写…" : "重新生成"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
