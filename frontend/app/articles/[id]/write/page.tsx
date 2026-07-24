import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { WritingStudio } from "@/components/writing-studio";
import { ApiError, getArticle } from "@/lib/api";

interface WritingRouteProps {
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

export async function generateMetadata({ params }: WritingRouteProps): Promise<Metadata> {
  const { id } = await params;
  const article = await loadArticle(id);
  return { title: `写作 · ${article.title}` };
}

export default async function WritingPage({ params }: WritingRouteProps) {
  const { id } = await params;
  const article = await loadArticle(id);
  return (
    <main id="main-content" className="studio-page shell">
      <nav className="breadcrumb" aria-label="面包屑">
        <Link href={`/articles/${article.id}`}>热点详情</Link>
        <span>/</span>
        <span>写作工作台</span>
      </nav>
      <header className="studio-header">
        <p className="section-index">WRITING STUDIO / REFERENCE VOICE</p>
        <h1>从热点到观点</h1>
        <p>选一个真正值得写的角度就可以直接生成。模型参考你认可的推文节奏，但不照搬句子，也不替你编造经历。</p>
      </header>
      <WritingStudio article={article} />
    </main>
  );
}
