import type {
  ArticleDetail,
  ArticlePage,
  OpenSourceStatus,
  RadarEditionList,
  SearchPage,
  TechnicalCategory,
  TopicList,
} from "./types";

const API_BASE = (
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(`API request failed with status ${status}`);
  }
}

export interface ArticleQuery {
  category?: TechnicalCategory;
  cursor?: string;
  dateFrom?: string;
  dateTo?: string;
  edition?: string;
  importanceMin?: string;
  limit?: number;
  openSourceStatus?: OpenSourceStatus;
  source?: string;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return (await response.json()) as T;
}

export function getArticles(query: ArticleQuery = {}): Promise<ArticlePage> {
  return apiFetch<ArticlePage>(
    `/articles${queryString({
      category: query.category,
      cursor: query.cursor,
      date_from: query.dateFrom,
      date_to: query.dateTo,
      edition: query.edition,
      importance_min: query.importanceMin,
      limit: query.limit,
      open_source_status: query.openSourceStatus,
      source: query.source,
    })}`,
  );
}

export function getArticle(id: string): Promise<ArticleDetail> {
  return apiFetch<ArticleDetail>(`/articles/${encodeURIComponent(id)}`);
}

export function getTopics(query: ArticleQuery = {}): Promise<TopicList> {
  return apiFetch<TopicList>(`/topics${queryString({ edition: query.edition })}`);
}

export function getRadarEditions(): Promise<RadarEditionList> {
  return apiFetch<RadarEditionList>("/radar-editions");
}

export function searchArticles(
  query: string,
  filters: ArticleQuery = {},
): Promise<SearchPage> {
  return apiFetch<SearchPage>(
    `/search${queryString({
      q: query,
      category: filters.category,
      cursor: filters.cursor,
      importance_min: filters.importanceMin,
      limit: filters.limit,
      open_source_status: filters.openSourceStatus,
      source: filters.source,
    })}`,
  );
}
