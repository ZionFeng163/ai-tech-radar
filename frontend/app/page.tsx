import { ArticleCard } from "@/components/article-card";
import { FilterBar } from "@/components/filter-bar";
import { PaginationLink } from "@/components/pagination-link";
import { TopicGrid } from "@/components/topic-grid";
import { getArticles, getTopics } from "@/lib/api";
import { formatScore } from "@/lib/format";
import type { OpenSourceStatus, TechnicalCategory } from "@/lib/types";

interface HomeSearchParams {
  category?: TechnicalCategory;
  cursor?: string;
  importance_min?: string;
  open_source_status?: OpenSourceStatus;
  source?: string;
}

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<HomeSearchParams>;
}) {
  const filters = await searchParams;
  const [articlePage, topicList] = await Promise.all([
    getArticles({
      category: filters.category,
      cursor: filters.cursor,
      importanceMin: filters.importance_min,
      limit: 9,
      openSourceStatus: filters.open_source_status,
      source: filters.source,
    }),
    getTopics(),
  ]);
  const [featured, ...articles] = articlePage.items;
  const averageImportance = topicList.items.length
    ? topicList.items.reduce((sum, topic) => sum + (topic.average_importance ?? 0), 0) /
      topicList.items.length
    : null;
  const pageHref = buildHref(filters);

  return (
    <main id="main-content">
      <section className="hero shell">
        <div className="hero-copy">
          <p className="kicker">DAILY DEEP LEARNING INTELLIGENCE · 上海</p>
          <h1>把每天的 AI 噪声，压缩成值得追踪的信号。</h1>
          <p className="hero-intro">
            聚合论文、开源项目、模型与数据集，用中文解释它为何重要，而不只是重复发生了什么。
          </p>
        </div>
        <div className="hero-stats" aria-label="雷达概览">
          <div>
            <strong>{topicList.items.reduce((sum, topic) => sum + topic.article_count, 0)}</strong>
            <span>已分析信号</span>
          </div>
          <div>
            <strong>{topicList.items.length}</strong>
            <span>技术分类</span>
          </div>
          <div>
            <strong>{formatScore(averageImportance)}</strong>
            <span>平均重要性</span>
          </div>
        </div>
      </section>

      <section className="signal-section shell" aria-labelledby="signals-title">
        <div className="section-heading">
          <div>
            <p className="section-index">01 / SIGNALS</p>
            <h2 id="signals-title">最新技术信号</h2>
          </div>
          <p>{articlePage.items.length} 条结果 · 查询 {articlePage.page.query_ms.toFixed(1)} ms</p>
        </div>

        <FilterBar
          category={filters.category}
          importanceMin={filters.importance_min}
          openSourceStatus={filters.open_source_status}
          source={filters.source}
        />

        {featured ? (
          <div className="article-stream">
            <ArticleCard article={featured} featured />
            {articles.map((article, index) => (
              <ArticleCard article={article} index={index} key={article.id} />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <strong>当前筛选下没有信号</strong>
            <p>尝试放宽分类、来源或重要性条件。</p>
          </div>
        )}
        <PaginationLink cursor={articlePage.page.next_cursor} href={pageHref} />
      </section>

      <section className="topics-section shell" id="topics" aria-labelledby="topics-title">
        <div className="section-heading">
          <div>
            <p className="section-index">02 / TOPICS</p>
            <h2 id="topics-title">按技术方向追踪</h2>
          </div>
          <p>从模型底座到工程部署，观察信号正在向哪里聚集。</p>
        </div>
        <TopicGrid topics={topicList.items} />
      </section>
    </main>
  );
}

function buildHref(filters: HomeSearchParams): string {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.importance_min) params.set("importance_min", filters.importance_min);
  if (filters.open_source_status) {
    params.set("open_source_status", filters.open_source_status);
  }
  if (filters.source) params.set("source", filters.source);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}
