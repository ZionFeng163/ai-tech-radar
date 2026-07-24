"use client";

import { useEffect, useRef, useState } from "react";

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
  { value: "short_post", label: "单条短帖", note: "一个判断，一项证据，一个含义" },
  { value: "thread", label: "短 Thread", note: "4–6 条，完整走完论证" },
  { value: "article", label: "X 长文", note: "约 1200–2500 个汉字" },
];

type Operation = "init" | "angles" | "draft" | "save" | "review" | null;

export function WritingStudio({ article }: { article: ArticleDetail }) {
  const initialized = useRef(false);
  const [project, setProject] = useState<WritingProject | null>(null);
  const [selectedAngle, setSelectedAngle] = useState("");
  const [format, setFormat] = useState<WritingFormat>("thread");
  const [humanInput, setHumanInput] = useState<HumanInput>(EMPTY_INPUT);
  const [draft, setDraft] = useState("");
  const [operation, setOperation] = useState<Operation>("init");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

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
    setHumanInput(next.human_input ?? EMPTY_INPUT);
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

      <section className="studio-step">
        <div className="studio-step-heading">
          <div>
            <p className="section-index">01 / EDITORIAL ANGLES</p>
            <h2>先决定写什么，不急着成稿</h2>
          </div>
          <button className="secondary-button" disabled={operation !== null} onClick={generateAngles}>
            {operation === "angles" ? "正在分析三个角度…" : project.angle_options.length ? "重新生成角度" : "生成三个角度"}
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
                <span><small>变化</small>{angle.change}</span>
                <span><small>张力</small>{angle.tension}</span>
                <span><small>反方</small>{angle.counterargument}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="studio-empty">模型会提出技术机制、产业变化和实际使用者三个方向。你选择之后才会写正文。</p>
        )}
      </section>

      {project.angle_options.length ? (
        <section className="studio-step">
          <p className="section-index">02 / YOUR POINT OF VIEW</p>
          <h2>把真实的你放进去</h2>
          <p className="studio-help">都可以留空，但模型绝不会替你编造亲历。哪怕只补一句真实判断，成稿也会明显不同。</p>
          <div className="human-input-grid">
            <label>
              <span>我真正想说的是</span>
              <textarea value={humanInput.core_take} onChange={(event) => setHumanInput({ ...humanInput, core_take: event.target.value })} placeholder="例如：我觉得竞争重点已经不是能力，而是让开发者形成工作流依赖。" />
            </label>
            <label>
              <span>我亲自观察到的现象</span>
              <textarea value={humanInput.personal_observation} onChange={(event) => setHumanInput({ ...humanInput, personal_observation: event.target.value })} placeholder="只写真实发生过的使用体验、对话或判断。" />
            </label>
            <label>
              <span>我不同意主流观点的地方</span>
              <textarea value={humanInput.disagreement} onChange={(event) => setHumanInput({ ...humanInput, disagreement: event.target.value })} placeholder="没有也可以留空，不需要为了显得独特而强行反对。" />
            </label>
          </div>

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
            {operation === "draft" ? "正在组织论证并写作…" : project.draft_content ? "按当前观点重新生成" : "生成第一版正文"}
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
