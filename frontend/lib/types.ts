export type ArticleKind =
  | "paper"
  | "code_repository"
  | "release"
  | "model"
  | "dataset"
  | "blog_post"
  | "news";

export type TechnicalCategory =
  | "foundation_models"
  | "training"
  | "inference"
  | "agents"
  | "multimodal"
  | "computer_vision"
  | "nlp"
  | "speech_audio"
  | "robotics"
  | "data"
  | "evaluation"
  | "infrastructure"
  | "safety"
  | "other";

export type OpenSourceStatus = "open" | "partial" | "closed" | "unknown";

export interface SourceReference {
  slug: string;
  name: string;
  item_url: string;
}

export interface AuthorReference {
  name: string;
  url: string | null;
}

export interface ArticleSummary {
  id: string;
  kind: ArticleKind;
  canonical_url: string | null;
  title: string;
  summary: string | null;
  primary_category: TechnicalCategory | null;
  tags: string[];
  importance_score: number | null;
  credibility_score: number | null;
  open_source_status: OpenSourceStatus | null;
  published_at: string;
  event_cluster_id: string | null;
  sources: SourceReference[];
  authors: AuthorReference[];
}

export interface ArticleDetail extends ArticleSummary {
  content: string | null;
  license: string | null;
  analysis: Record<string, unknown>;
  analysis_schema_version: string | null;
  analyzed_at: string | null;
  source_tags: string[];
}

export interface PageMetadata {
  limit: number;
  has_more: boolean;
  next_cursor: string | null;
  query_ms: number;
}

export interface ArticlePage {
  items: ArticleSummary[];
  page: PageMetadata;
}

export interface SearchResult extends ArticleSummary {
  search_score: number;
}

export interface SearchPage {
  query: string;
  items: SearchResult[];
  page: PageMetadata;
}

export interface TopicSummary {
  category: TechnicalCategory;
  article_count: number;
  average_importance: number | null;
  latest_published_at: string;
}

export interface TopicList {
  items: TopicSummary[];
  query_ms: number;
}
