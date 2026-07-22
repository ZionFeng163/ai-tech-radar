import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, getArticle } from "@/lib/api";
import { DeepAnalysisButton } from "@/components/deep-analysis-button";
import {
  categoryLabels,
  formatDate,
  formatScore,
  kindLabels,
  openSourceLabels,
} from "@/lib/format";

interface ArticleRouteProps {
  params: Promise<{ id: string }>;
}

async function loadArticle(id: string) {
  try {
    return await getArticle(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({ params }: ArticleRouteProps): Promise<Metadata> {
  const { id } = await params;
  const article = await loadArticle(id);
  return {
    title: article.title,
    description: article.summary ?? "AI Tech Radar 技术信号深度分析",
  };
}

export default async function ArticlePage({ params }: ArticleRouteProps) {
  const { id } = await params;
  const article = await loadArticle(id);
  const analysisSections = [
    ["核心创新", article.analysis.core_innovations],
    ["与既有工作的差异", article.analysis.differences_from_prior_work],
    ["应用场景", article.analysis.application_scenarios],
    ["为什么值得关注", article.analysis.why_it_matters],
  ] as const;

  return (
    <main id="main-content" className="detail-main">
      <article className="article-detail shell">
        <nav className="breadcrumb" aria-label="面包屑">
          <Link href="/">今日信号</Link>
          <span>/</span>
          <span>{article.primary_category ? categoryLabels[article.primary_category] : "待分类"}</span>
        </nav>

        <header className="detail-header">
          <div className="detail-meta article-meta">
            <span>{kindLabels[article.kind]}</span>
            <time dateTime={article.published_at}>{formatDate(article.published_at)}</time>
            <span>{openSourceLabels[article.open_source_status ?? "unknown"]}</span>
          </div>
          <h1>{article.title}</h1>
          {article.summary ? <p className="detail-deck">{article.summary}</p> : null}
          <div className="detail-scoreboard">
            <div><span>重要性</span><strong>{formatScore(article.importance_score)}</strong></div>
            <div><span>可信度</span><strong>{formatScore(article.credibility_score)}</strong></div>
            <div><span>技术方向</span><strong>{article.primary_category ? categoryLabels[article.primary_category] : "待分类"}</strong></div>
          </div>
        </header>

        <div className="detail-layout">
          <div className="detail-content">
            {article.analysis_depth === "brief" ? (
              <DeepAnalysisButton articleId={article.id} />
            ) : analysisSections.map(([title, value], index) => {
              const items = toTextItems(value);
              if (!items.length) return null;
              return (
                <section className="analysis-section" key={title}>
                  <p className="section-index">{String(index + 1).padStart(2, "0")} / ANALYSIS</p>
                  <h2>{title}</h2>
                  {items.length === 1 ? <p>{items[0]}</p> : (
                    <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
                  )}
                </section>
              );
            })}

            {article.content ? (
              <section className="analysis-section raw-content">
                <p className="section-index">SOURCE / ABSTRACT</p>
                <h2>原始内容摘要</h2>
                {article.content.split(/\n{2,}/).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              </section>
            ) : null}
          </div>

          <aside className="detail-aside">
            <section>
              <h2>来源</h2>
              <ul className="source-list">
                {article.sources.map((source) => (
                  <li key={`${source.slug}-${source.item_url}`}>
                    <a href={source.item_url} target="_blank" rel="noreferrer">{source.name} ↗</a>
                  </li>
                ))}
                {article.canonical_url ? (
                  <li><a href={article.canonical_url} target="_blank" rel="noreferrer">原始链接 ↗</a></li>
                ) : null}
              </ul>
            </section>
            {article.authors.length ? (
              <section>
                <h2>作者</h2>
                <p>{article.authors.map((author) => author.name).join(" · ")}</p>
              </section>
            ) : null}
            {article.tags.length ? (
              <section>
                <h2>标签</h2>
                <div className="tag-list">{article.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              </section>
            ) : null}
            <section>
              <h2>分析状态</h2>
              <p>{article.analysis_depth === "deep" ? "深度分析已生成" : "快速概览 · 可按需生成深度分析"}</p>
            </section>
          </aside>
        </div>
      </article>
    </main>
  );
}

function toTextItems(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  }
  return [];
}
