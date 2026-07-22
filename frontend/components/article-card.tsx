import Link from "next/link";

import { categoryLabels, formatDate, formatScore, kindLabels } from "@/lib/format";
import type { ArticleSummary } from "@/lib/types";

interface ArticleCardProps {
  article: ArticleSummary;
  featured?: boolean;
  index?: number;
}

export function ArticleCard({ article, featured = false, index }: ArticleCardProps) {
  const category = article.primary_category
    ? categoryLabels[article.primary_category]
    : "待分类";
  const source = article.sources[0]?.name ?? "未知来源";

  return (
    <article className={featured ? "article-card article-card-featured" : "article-card"}>
      <div className="article-card-index" aria-hidden="true">
        {featured ? "FEATURED" : String((index ?? 0) + 1).padStart(2, "0")}
      </div>
      <div className="article-card-body">
        <div className="article-meta">
          <span>{kindLabels[article.kind]}</span>
          <span>{category}</span>
          <time dateTime={article.published_at}>{formatDate(article.published_at)}</time>
        </div>
        <h2>
          <Link href={`/articles/${article.id}`}>{article.title}</Link>
        </h2>
        {article.summary ? <p className="article-summary">{article.summary}</p> : null}
        <div className="article-footer">
          <span className="source-name">{source}</span>
          <div className="score" aria-label={`重要性评分 ${formatScore(article.importance_score)}`}>
            <span>重要性</span>
            <strong>{formatScore(article.importance_score)}</strong>
            <span className="score-track" aria-hidden="true">
              <span style={{ width: `${(article.importance_score ?? 0) * 10}%` }} />
            </span>
          </div>
        </div>
      </div>
    </article>
  );
}
