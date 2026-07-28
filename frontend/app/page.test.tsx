import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getArticles, getRadarEditions, getTopics } from "@/lib/api";

import Home from "./page";

vi.mock("@/lib/api", () => ({
  getArticles: vi.fn(),
  getRadarEditions: vi.fn(),
  getTopics: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
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
  novelty_summary: "新意在于把原本分离的调度环节合并，减少了重复开销。",
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
    vi.mocked(getRadarEditions).mockResolvedValue({
      items: [{
        id: "edition-1",
        captured_at: "2026-07-22T09:00:00Z",
        finished_at: "2026-07-22T09:02:00Z",
        status: "complete",
        article_count: 1,
        source_results: [],
        progress: {
          stage: "complete",
          completed: 1,
          total: 1,
          message: "已完成",
        },
        error_summary: null,
      }],
    });
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
    expect(
      screen.getByText("把原本分离的调度环节合并，减少了重复开销。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(article.novelty_summary)).not.toBeInTheDocument();
    expect(screen.getByText("数据清理")).toBeInTheDocument();
  });

  it("explains why a captured edition has no visible signals", async () => {
    vi.mocked(getRadarEditions).mockResolvedValue({
      items: [{
        id: "edition-failed",
        captured_at: "2026-07-28T02:01:00Z",
        finished_at: "2026-07-28T02:05:00Z",
        status: "failed",
        article_count: 37,
        source_results: [{
          source: "arxiv",
          status: "failed",
          error: "HTTP 429",
        }],
        progress: {
          stage: "failed",
          completed: 0,
          total: 37,
          message: "百炼免费额度已耗尽",
          collected_count: 37,
          analyzed_count: 6,
          visible_count: 0,
          analysis_failed: 1,
          analysis_skipped: 30,
        },
        error_summary: "百炼免费额度已耗尽，请调整账号设置后重试。",
      }],
    });
    vi.mocked(getArticles).mockResolvedValue({
      items: [],
      page: { limit: 18, has_more: false, next_cursor: null, query_ms: 2.1 },
    });
    vi.mocked(getTopics).mockResolvedValue({ items: [], query_ms: 1.2 });

    render(await Home({
      searchParams: Promise.resolve({ edition: "edition-failed" }),
    }));

    expect(screen.getByText("本期处理失败，没有发布内容")).toBeInTheDocument();
    expect(screen.getByText("抓取 37 条")).toBeInTheDocument();
    expect(screen.getByText("完成概览 6 条")).toBeInTheDocument();
    expect(screen.getByText("可展示 0 条")).toBeInTheDocument();
    expect(screen.getByText("arxiv：请求频率受限")).toBeInTheDocument();
    expect(getArticles).toHaveBeenCalledWith(
      expect.objectContaining({ edition: "edition-failed" }),
    );
  });
});
