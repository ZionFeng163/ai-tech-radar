"use client";

import { useEffect, useRef, useState } from "react";

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
  { value: "thread", label: "短 Thread", note: "4–6 条，每条可独立阅读" },
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
  const [operation, setOperation] = useState<Operation>("init");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const hasSourceExcerpt = (article.content?.trim().length ?? 0) >= SOURCE_EXCERPT_MIN_CHARACTERS;

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void requestProject(`/api/articles/${encodeURIComponent(article.id)}/writing-project`, {
      method: "POST",
    }).then(hydrate).catch(showError);
  }, [article.id]);

  function hydrate(next: WritingProject) {
    setProject(next);
    setSelectedAngle(next.selected_angle_id ?? next.angle_options[0]?.id ?? "");
    setFormat(next.output_format);
    setHumanInput({
      ...EMPTY_INPUT,
      core_take: next.human_input?.core_take ?? "",
    });
    setDraft(next.draft_content ?? "");
    setOperation(null);
    setError("");
  }

  function showError(reason: unknown) {
    setOperation(null);
    setError(reason instanceof Error ? reason.message : "操作失败，请稍后重试");
  }

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
        setFormat(recommended.recommended_format);
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
    const saved = draft === project.draft_content ? project : await saveDraft();
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
          {article.analysis_depth === "deep" && hasSourceExcerpt ? (
            <>
              <h2>深度分析已接入写作</h2>
              <p>
                新生成的角度会带上技术机制、新意和应用判断。
                {project.angle_options.length ? "现有角度和草稿不会被覆盖；点“重新生成角度”后才会使用这些新资料。" : "现在可以直接生成写作角度。"}
              </p>
            </>
          ) : hasSourceExcerpt ? (
            <>
              <h2>当前使用原始资料与快速概览</h2>
              <p>现在也能直接写；如果准备写技术 Thread 或长文，先补深度分析通常会让论据和技术解释更完整。</p>
            </>
          ) : (
            <>
              <h2>当前是薄资料写作模式</h2>
              <p>这条热点主要只有标题和热度数字。为了避免 AI 自我引用，深度分析不会被当成原始事实；短推文可以直接生成，长文建议先补充可靠来源。</p>
            </>
          )}
        </div>
        {article.analysis_depth === "brief" && hasSourceExcerpt ? (
          <DeepAnalysisButton articleId={article.id} variant="writing" />
        ) : null}
      </section>

      <section className="studio-step">
        <div className="studio-step-heading">
          <div>
            <p className="section-index">01 / EDITORIAL ANGLES</p>
            <h2>先决定写什么，不急着成稿</h2>
          </div>
          <button className="secondary-button" disabled={operation !== null} onClick={generateAngles}>
            {operation === "angles" ? "正在分析写作角度…" : project.angle_options.length ? "重新生成角度" : "生成写作角度"}
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
          <p className="studio-empty">模型会根据资料完整度提出一到三个角度；资料很薄时只给一个有依据的方向。</p>
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
            {FORMAT_OPTIONS.map((option) => (
              <label className={format === option.value ? "is-selected" : ""} key={option.value}>
                <input type="radio" name="writing-format" value={option.value} checked={format === option.value} onChange={() => setFormat(option.value)} />
                <strong>{option.label}</strong>
                <span>{option.note}</span>
              </label>
            ))}
          </fieldset>
          <button className="action-button studio-generate" disabled={!selectedAngle || operation !== null} onClick={generateDraft}>
            {operation === "draft" ? "正在按参考风格写作…" : project.draft_content ? "按当前选择重新生成" : "直接生成第一版"}
          </button>
        </section>
      ) : null}

      {project.draft_content ? (
        <section className="studio-step studio-editor-section">
          <div className="studio-step-heading">
            <div>
              <p className="section-index">03 / DRAFT</p>
              <h2>这是草稿，不是答案</h2>
            </div>
            <span className="draft-count">{draft.length} 字符</span>
          </div>
          <textarea className="draft-editor" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="写作草稿" />
          <div className="studio-actions">
            <button className="secondary-button" disabled={operation !== null || draft === project.draft_content} onClick={saveDraft}>{operation === "save" ? "保存中…" : "保存修改"}</button>
            <button className="secondary-button" disabled={operation !== null} onClick={copyDraft}>{copied ? "已复制" : "复制正文"}</button>
            <button className="action-button" disabled={operation !== null || !draft.trim()} onClick={reviewDraft}>{operation === "review" ? "严格审校中…" : "检查事实与 AI 腔"}</button>
          </div>
        </section>
      ) : null}

      {project.review ? (
        <section className="studio-step studio-review">
          <p className="section-index">04 / EDITOR REVIEW</p>
          <h2>审校意见</h2>
          <p className="review-verdict">{project.review.verdict}</p>
          <div className="review-scores">
            <Score label="论点" value={project.review.thesis_clarity} />
            <Score label="原创认识" value={project.review.originality} />
            <Score label="技术清晰" value={project.review.technical_clarity} />
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
