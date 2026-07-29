"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DeepAnalysisButton } from "@/components/deep-analysis-button";
import type {
  ArticleDetail,
  HumanInput,
  WritingFormat,
  WritingProject,
} from "@/lib/types";

const EMPTY_INPUT: HumanInput = {
  core_take: "",
  personal_observation: "",
  disagreement: "",
};

const FORMAT_OPTIONS: Array<{ value: WritingFormat; label: string; note: string }> = [
  { value: "short_post", label: "短观点推文", note: "约 180–300 字，只讲一个认识" },
  { value: "thread", label: "短 Thread", note: "3–4 条，每条都有事实或判断" },
  { value: "article", label: "X 长文", note: "约 1200–2500 个汉字" },
];

const SOURCE_EXCERPT_MIN_CHARACTERS = 200;

type Operation = "init" | "angles" | "draft" | "save" | "review" | null;

export function WritingStudio({ article }: { article: ArticleDetail }) {
  const initialized = useRef(false);
  const [project, setProject] = useState<WritingProject | null>(null);
  const [selectedAngle, setSelectedAngle] = useState("");
  const [format, setFormat] = useState<WritingFormat>("short_post");
  const [humanInput, setHumanInput] = useState<HumanInput>(EMPTY_INPUT);
  const [draft, setDraft] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [operation, setOperation] = useState<Operation>("init");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const hasSourceExcerpt = (article.content?.trim().length ?? 0) >= SOURCE_EXCERPT_MIN_CHARACTERS;
  const deepAnalysisReady = article.analysis_depth === "deep";

  const hydrate = useCallback((next: WritingProject) => {
    setProject(next);
    setSelectedAngle(next.selected_angle_id ?? next.angle_options[0]?.id ?? "");
    setFormat(!hasSourceExcerpt && next.output_format === "article" ? "short_post" : next.output_format);
    setHumanInput({
      ...EMPTY_INPUT,
      core_take: next.human_input?.core_take ?? "",
    });
    const content = next.final_content ?? next.draft_content ?? "";
    setDraft(content);
    setSavedContent(content);
    setOperation(null);
    setError("");
  }, [hasSourceExcerpt]);

  const showError = useCallback((reason: unknown) => {
    setOperation(null);
    setError(reason instanceof Error ? reason.message : "操作失败，请稍后重试");
  }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void requestProject(`/api/articles/${encodeURIComponent(article.id)}/writing-project`, {
      method: "POST",
    }).then(hydrate).catch(showError);
  }, [article.id, hydrate, showError]);

  async function generateAngles() {
    if (!project) return;
    setOperation("angles");
    setError("");
    try {
      const next = await requestProject(`/api/writing-projects/${project.id}/angles`, {
        method: "POST",
      });
      hydrate(next);
      const recommended = next.angle_options[0];
      if (recommended) {
        setSelectedAngle(recommended.id);
        setFormat(!hasSourceExcerpt && recommended.recommended_format === "article" ? "short_post" : recommended.recommended_format);
      }
    } catch (reason) {
      showError(reason);
    }
  }

  async function generateDraft() {
    if (!project || !selectedAngle) return;
    setOperation("draft");
    setError("");
    try {
      const next = await requestProject(`/api/writing-projects/${project.id}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          angle_id: selectedAngle,
          output_format: format,
          human_input: humanInput,
        }),
      });
      hydrate(next);
    } catch (reason) {
      showError(reason);
    }
  }

  async function saveDraft() {
    if (!project || !draft.trim()) return null;
    setOperation("save");
    setError("");
    try {
      const next = await requestProject(`/api/writing-projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft_content: draft }),
      });
      hydrate(next);
      return next;
    } catch (reason) {
      showError(reason);
      return null;
    }
  }

  async function reviewDraft() {
    if (!project || !draft.trim()) return;
    const saved =
      draft === savedContent && !project.final_content ? project : await saveDraft();
    if (!saved) return;
    setOperation("review");
    setError("");
    try {
      const next = await requestProject(`/api/writing-projects/${saved.id}/review`, {
        method: "POST",
      });
      hydrate(next);
    } catch (reason) {
      showError(reason);
    }
  }

  async function copyDraft() {
    await navigator.clipboard.writeText(draft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  if (operation === "init") {
    return <div className="studio-loading">正在打开写作工作台…</div>;
  }

  if (!project) {
    return <div className="studio-error">{error || "写作工作台暂时不可用"}</div>;
  }

  return (
    <div className="writing-studio">
      <section className="studio-source">
        <p className="section-index">SOURCE / SIGNAL</p>
        <h2>{article.title}</h2>
        <p>{article.summary ?? article.technical_overview ?? "当前热点暂无摘要。"}</p>
        <div className="studio-source-facts">
          {article.novelty_summary ? <span>新意：{article.novelty_summary}</span> : null}
          {article.heat_reasons.slice(0, 2).map((reason) => <span key={reason}>热度：{reason}</span>)}
        </div>
      </section>

      <section className={`studio-source-status ${article.analysis_depth === "deep" ? "is-deep" : ""}`}>
        <div>
          <p className="section-index">SOURCE QUALITY / WRITING INPUT</p>
          {deepAnalysisReady && hasSourceExcerpt ? (
            <>
              <h2>深度分析已接入写作</h2>
              <p>
                新生成的角度会带上技术机制、新意和应用判断。
                {project.angle_options.length ? "现有角度和草稿不会被覆盖；点“重新生成角度”后才会使用这些新资料。" : "现在可以直接生成写作角度。"}
              </p>
            </>
          ) : deepAnalysisReady ? (
            <>
              <h2>深度分析完成，但原始证据仍然较薄</h2>
              <p>可以生成克制的短推文；分析中的推断只会作为观点线索，不会冒充原文事实。由于缺少可靠正文，长文暂时不可生成。</p>
            </>
          ) : hasSourceExcerpt ? (
            <>
              <h2>当前使用原始资料与快速概览</h2>
              <p>现在也能直接写；如果准备写技术 Thread 或长文，先补深度分析通常会让论据和技术解释更完整。</p>
            </>
          ) : (
            <>
              <h2>写作前需要先完成深度分析</h2>
              <p>这条热点的原始正文较薄。分析会先划清事实与推断，再决定能写到什么程度；平台排名和互动数字只用于选题，不会写进正文。</p>
            </>
          )}
        </div>
        {!deepAnalysisReady ? (
          <DeepAnalysisButton articleId={article.id} variant="writing" />
        ) : null}
      </section>

      <section className="studio-step">
        <div className="studio-step-heading">
          <div>
            <p className="section-index">01 / EDITORIAL ANGLES</p>
            <h2>先决定写什么，不急着成稿</h2>
          </div>
          <button className="secondary-button" disabled={operation !== null || !deepAnalysisReady} onClick={generateAngles}>
            {operation === "angles" ? "正在分析写作角度…" : !deepAnalysisReady ? "请先完成深度分析" : project.angle_options.length ? "重新生成角度" : "生成写作角度"}
          </button>
        </div>

        {project.angle_options.length ? (
          <div className="angle-grid">
            {project.angle_options.map((angle) => (
              <label className={`angle-card ${selectedAngle === angle.id ? "is-selected" : ""}`} key={angle.id}>
                <input
                  type="radio"
                  name="writing-angle"
                  value={angle.id}
                  checked={selectedAngle === angle.id}
                  onChange={() => {
                    setSelectedAngle(angle.id);
                    setFormat(angle.recommended_format);
                  }}
                />
                <span className="angle-card-top"><strong>{angle.label}</strong><b>{angle.value_score.toFixed(1)}</b></span>
                <em>{angle.thesis}</em>
                <span><small>为什么值得写</small>{angle.reader_gain}</span>
                <span><small>资料支点</small>{angle.evidence.slice(0, 2).join("；")}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="studio-empty">模型会提出三个不同方向；资料较薄时三个角度会共享同一条严格事实边界，不会为了凑数补写新事实。</p>
        )}
      </section>

      {project.angle_options.length ? (
        <section className="studio-step">
          <p className="section-index">02 / OPTIONAL EMPHASIS</p>
          <h2>有想强调的就补一句</h2>
          <p className="studio-help">完全可以留空。模型会根据资料和参考风格自己完成信息取舍，也不会假装你亲自用过。</p>
          <label className="emphasis-input">
            <span>可选：这次特别想强调什么</span>
            <textarea value={humanInput.core_take} onChange={(event) => setHumanInput({ ...EMPTY_INPUT, core_take: event.target.value })} placeholder="例如：我更关心它能否在普通硬件上真正跑起来。没有就直接生成。" />
          </label>

          <fieldset className="format-picker">
            <legend>输出形式</legend>
            <p className="studio-help">默认面向对技术感兴趣的普通读者：保留关键机制，但第一次出现的术语会立即用白话解释。</p>
            {FORMAT_OPTIONS.map((option) => (
              <label className={format === option.value ? "is-selected" : ""} key={option.value}>
                <input type="radio" name="writing-format" value={option.value} checked={format === option.value} disabled={!hasSourceExcerpt && option.value === "article"} onChange={() => setFormat(option.value)} />
                <strong>{option.label}</strong>
                <span>{!hasSourceExcerpt && option.value === "article" ? "原始资料不足，补充可靠来源后开放" : option.note}</span>
              </label>
            ))}
          </fieldset>
          <button className="action-button studio-generate" disabled={!selectedAngle || operation !== null || !deepAnalysisReady} onClick={generateDraft}>
            {operation === "draft" ? "正在写作、核验并安全改稿…" : project.draft_content ? "按当前选择重新生成" : "生成核验版正文"}
          </button>
        </section>
      ) : null}

      {project.draft_content ? (
        <section className="studio-step studio-editor-section">
          <div className="studio-step-heading">
            <div>
              <p className="section-index">03 / {project.final_content ? "VERIFIED COPY" : "DRAFT"}</p>
              <h2>{project.final_content ? "核验后的可发布稿" : "初稿仍需核验"}</h2>
            </div>
            <span className="draft-count">{draft.length} 字符</span>
          </div>
          {project.final_content ? (
            <p className="studio-help">下面默认展示经过独立主张核验的版本。你修改后，系统会把它重新视为草稿，需要再次核验。</p>
          ) : null}
          <textarea className="draft-editor" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label={project.final_content ? "核验后正文" : "写作草稿"} />
          <div className="studio-actions">
            <button className="secondary-button" disabled={operation !== null || draft === savedContent} onClick={saveDraft}>{operation === "save" ? "保存中…" : "保存修改"}</button>
            <button className="secondary-button" disabled={operation !== null} onClick={copyDraft}>{copied ? "已复制" : "复制正文"}</button>
            <button className="action-button" disabled={operation !== null || !draft.trim()} onClick={reviewDraft}>{operation === "review" ? "逐条核验并改稿中…" : project.final_content ? "重新核验当前正文" : "核验并生成安全稿"}</button>
          </div>
          {project.error_summary ? (
            <div className="studio-warning" role="status">
              <strong>草稿已保留，未生成可发布稿</strong>
              <p>{project.error_summary}</p>
            </div>
          ) : null}
          {project.final_content && project.verification.publishable ? (
            <div className="verification-summary" role="status">
              <strong>已通过独立主张核验</strong>
              <p>{project.verification.summary}</p>
              <span>{project.claim_ledger.length} 条主张已绑定证据或明确标为作者判断</span>
              {project.verification.changes?.length ? (
                <details>
                  <summary>查看本次改动</summary>
                  <ul>{project.verification.changes.map((change) => <li key={change}>{change}</li>)}</ul>
                </details>
              ) : null}
            </div>
          ) : null}
          {project.final_content && project.draft_content !== project.final_content ? (
            <details className="original-draft">
              <summary>查看核验前初稿</summary>
              <pre>{project.draft_content}</pre>
            </details>
          ) : null}
        </section>
      ) : null}

      {project.review ? (
        <section className="studio-step studio-review">
          <p className="section-index">04 / FINAL REVIEW</p>
          <h2>{project.final_content ? "最终稿编辑检查" : "初稿审校意见"}</h2>
          <p className="review-verdict">{project.review.verdict}</p>
          <div className="review-scores">
            <Score label="论点" value={project.review.thesis_clarity} />
            <Score label="原创认识" value={project.review.originality} />
            <Score label="技术清晰" value={project.review.technical_clarity} />
            <Score label="公众可读" value={project.review.accessibility} />
            <Score label="人味" value={project.review.human_voice} />
          </div>
          {project.review.issues.length ? (
            <div className="review-issues">
              {project.review.issues.map((issue, index) => (
                <article key={`${issue.category}-${index}`}>
                  <span>{issue.severity} · {issue.category}</span>
                  {issue.quote ? <blockquote>{issue.quote}</blockquote> : null}
                  <p>{issue.problem}</p>
                  <strong>建议：{issue.suggestion}</strong>
                </article>
              ))}
            </div>
          ) : <p className="studio-empty">没有需要强行修改的问题，可以由你做最后判断。</p>}
        </section>
      ) : null}

      {error ? <div className="studio-error" role="alert">{error}</div> : null}
    </div>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{value.toFixed(1)}</strong></div>;
}

async function requestProject(path: string, init: RequestInit): Promise<WritingProject> {
  const response = await fetch(path, init);
  const payload = (await response.json().catch(() => ({}))) as WritingProject & { detail?: string };
  if (!response.ok) throw new Error(payload.detail ?? `请求失败（${response.status}）`);
  return payload;
}
