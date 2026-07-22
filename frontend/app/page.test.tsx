import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getArticles, getTopics } from "@/lib/api";

import Home from "./page";

vi.mock("@/lib/api", () => ({
  getArticles: vi.fn(),
  getTopics: vi.fn(),
}));

const article = {
  id: "signal-1",
  kind: "paper" as const,
  canonical_url: "https://example.com/paper",
  title: "高效推理的新型注意力机制",
  summary: "在长上下文任务中减少显存占用，同时保持模型质量。",
  primary_category: "inference" as const,
  tags: ["attention"],
  importance_score: 8.6,
  heat_score: 8.1,
  signal_type: "technical" as const,
  technical_overview: "通过新的推理调度方法降低模型服务延迟。",
  novelty_summary: "把原本分离的调度环节合并，减少了重复开销。",
  heat_reasons: ["可能直接降低开发者部署成本"],
  credibility_score: 9.1,
  open_source_status: "open" as const,
  published_at: "2026-07-22T08:00:00Z",
  event_cluster_id: null,
  sources: [{ slug: "arxiv", name: "arXiv", item_url: "https://example.com/paper" }],
  authors: [{ name: "Radar Lab", url: null }],
};

describe("Home", () => {
  beforeEach(() => {
    vi.mocked(getArticles).mockResolvedValue({
      items: [article],
      page: { limit: 9, has_more: false, next_cursor: null, query_ms: 4.2 },
    });
    vi.mocked(getTopics).mockResolvedValue({
      items: [{
        category: "inference",
        article_count: 1,
        average_importance: 8.6,
        latest_published_at: article.published_at,
      }],
      query_ms: 2.1,
    });
  });

  it("renders live radar data and topic navigation", async () => {
    render(await Home({ searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("heading", { name: /把每天的 AI 噪声/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: article.title })).toHaveAttribute(
      "href",
      "/articles/signal-1",
    );
    expect(screen.getByRole("link", { name: /推理与部署/ })).toHaveAttribute(
      "href",
      "/topics/inference",
    );
  });
});
