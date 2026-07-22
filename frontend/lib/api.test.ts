import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getArticle, getArticles, searchArticles } from "./api";

describe("API client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("serializes article filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], page: {} }), { status: 200 }),
    );

    await getArticles({ category: "agents", importanceMin: "8", limit: 9 });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/articles?category=agents&importance_min=8&limit=9"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("encodes search and article identifiers", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }));

    await searchArticles("视觉 模型");
    await getArticle("paper/42");

    expect(fetchMock.mock.calls[0][0]).toContain("q=%E8%A7%86%E8%A7%89+%E6%A8%A1%E5%9E%8B");
    expect(fetchMock.mock.calls[1][0]).toContain("/articles/paper%2F42");
  });

  it("raises a typed error for failed requests", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 404 }));

    await expect(getArticle("missing")).rejects.toEqual(new ApiError(404));
  });
});
