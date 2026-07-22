import { ArticleCard } from "@/components/article-card";
import { FilterBar } from "@/components/filter-bar";
import { PaginationLink } from "@/components/pagination-link";
import { searchArticles } from "@/lib/api";
import type { OpenSourceStatus, TechnicalCategory } from "@/lib/types";

interface SearchParams {
  category?: TechnicalCategory;
  cursor?: string;
  importance_min?: string;
  open_source_status?: OpenSourceStatus;
  q?: string;
  source?: string;
}

export const metadata = {
  title: "搜索 · AI Tech Radar",
  description: "搜索 AI Tech Radar 收录的论文、模型、开源项目与数据集。",
};

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
  const results =
    query.length >= 2
      ? await searchArticles(query, {
          category: params.category,
          cursor: params.cursor,
          importanceMin: params.importance_min,
          limit: 12,
          openSourceStatus: params.open_source_status,
          source: params.source,
        })
      : null;
  const paginationHref = buildHref(params);

  return (
    <main id="main-content" className="shell subpage search-page">
      <header className="subpage-header search-header">
        <p className="section-index">SEARCH / FULL TEXT</p>
        <h1>搜索雷达信号</h1>
        <form className="search-form" action="/search" role="search">
          <label className="sr-only" htmlFor="search-q">
            输入关键词
          </label>
          <input
            id="search-q"
            name="q"
            type="search"
            defaultValue={query}
            placeholder="例如：transformer、推理、语音模型"
            minLength={2}
            required
            autoFocus
          />
          <button type="submit">开始搜索</button>
        </form>
      </header>

      {query.length >= 2 ? (
        <FilterBar
          action="/search"
          category={params.category}
          importanceMin={params.importance_min}
          openSourceStatus={params.open_source_status}
          query={query}
          source={params.source}
        />
      ) : null}

      {results ? (
        <section aria-labelledby="result-title">
          <div className="section-heading search-result-heading">
            <div>
              <p className="section-index">RESULTS</p>
              <h2 id="result-title">“{query}” 的搜索结果</h2>
            </div>
            <p>{results.items.length} 条结果 · {results.page.query_ms.toFixed(1)} ms</p>
          </div>
          {results.items.length ? (
            <div className="article-stream compact-stream">
              {results.items.map((article, index) => (
                <ArticleCard article={article} index={index} key={article.id} />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <strong>没有找到匹配的信号</strong>
              <p>尝试使用更短的技术名词，或移除部分筛选条件。</p>
            </div>
          )}
          <PaginationLink cursor={results.page.next_cursor} href={paginationHref} />
        </section>
      ) : (
        <div className="search-suggestions">
          <p>可以搜索</p>
          <span>模型名称</span>
          <span>论文关键词</span>
          <span>开源项目</span>
          <span>技术方向</span>
        </div>
      )}
    </main>
  );
}

function buildHref(params: SearchParams): string {
  const values = new URLSearchParams();
  if (params.q) values.set("q", params.q);
  if (params.category) values.set("category", params.category);
  if (params.importance_min) values.set("importance_min", params.importance_min);
  if (params.open_source_status) values.set("open_source_status", params.open_source_status);
  if (params.source) values.set("source", params.source);
  return `/search?${values.toString()}`;
}
