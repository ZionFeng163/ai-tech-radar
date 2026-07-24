import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getArticle } from "@/lib/api";

import ArticlePage from "./page";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  getArticle: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
  useRouter: () => ({ refresh: vi.fn() }),
}));

describe("ArticlePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders repeated source paragraphs without duplicate React keys", async () => {
    vi.mocked(getArticle).mockResolvedValue({
      id: "article-1",
      kind: "model",
      canonical_url: "https://example.com/model",
      title: "Example model",
      summary: "A useful model.",
      content: "Repeated code block\n\nUnique paragraph\n\nRepeated code block",
      license: "apache-2.0",
      primary_category: "speech_audio",
      tags: ["asr"],
      source_tags: ["automatic-speech-recognition"],
      importance_score: 8,
      heat_score: 7,
      signal_type: "technical",
      technical_overview: "Technical overview.",
      novelty_summary: "Novelty summary.",
      heat_reasons: ["Fast inference"],
      credibility_score: 9,
      open_source_status: "open",
      published_at: "2026-07-24T00:00:00Z",
      event_cluster_id: null,
      sources: [{ slug: "hugging-face", name: "Hugging Face Hub", item_url: "https://example.com/model" }],
      authors: [{ name: "Example Lab", url: null }],
      analysis: {},
      analysis_schema_version: "brief-v1",
      analyzed_at: "2026-07-24T01:00:00Z",
      analysis_depth: "brief",
    });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(await ArticlePage({ params: Promise.resolve({ id: "article-1" }) }));

    expect(screen.getAllByText("Repeated code block")).toHaveLength(2);
    expect(
      consoleError.mock.calls.some((call) => String(call[0]).includes("same key")),
    ).toBe(false);
  });
});
