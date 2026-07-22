import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArticleCard } from "@/components/article-card";
import { PaginationLink } from "@/components/pagination-link";
import { getArticles } from "@/lib/api";
import { categoryLabels } from "@/lib/format";
import type { TechnicalCategory } from "@/lib/types";

interface CategoryPageProps {
  params: Promise<{ category: string }>;
  searchParams: Promise<{ cursor?: string }>;
}

export async function generateMetadata({ params }: CategoryPageProps): Promise<Metadata> {
  const { category } = await params;
  if (!isCategory(category)) return {};
  return {
    title: `${categoryLabels[category]} · AI Tech Radar`,
    description: `追踪${categoryLabels[category]}方向的最新论文、模型、项目与技术进展。`,
  };
}

export default async function CategoryPage({ params, searchParams }: CategoryPageProps) {
  const [{ category }, query] = await Promise.all([params, searchParams]);
  if (!isCategory(category)) notFound();
  const articlePage = await getArticles({ category, cursor: query.cursor, limit: 12 });

  return (
    <main id="main-content" className="shell subpage">
      <nav className="breadcrumb" aria-label="面包屑">
        <Link href="/">首页</Link>
        <span>/</span>
        <span>技术分类</span>
      </nav>
      <header className="subpage-header">
        <p className="section-index">TOPIC / {category.toUpperCase()}</p>
        <h1>{categoryLabels[category]}</h1>
        <p>持续追踪这个方向的最新论文、模型、开源发布与工程实践。</p>
      </header>
      <div className="article-stream compact-stream">
        {articlePage.items.map((article, index) => (
          <ArticleCard article={article} index={index} key={article.id} />
        ))}
      </div>
      {articlePage.items.length === 0 ? (
        <div className="empty-state">
          <strong>这个方向还没有捕获到信号</strong>
          <p>下一轮采集和分析后会自动出现在这里。</p>
        </div>
      ) : null}
      <PaginationLink
        cursor={articlePage.page.next_cursor}
        href={`/topics/${category}`}
      />
    </main>
  );
}

function isCategory(value: string): value is TechnicalCategory {
  return value in categoryLabels;
}
