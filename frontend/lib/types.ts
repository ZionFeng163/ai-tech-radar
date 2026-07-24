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
export type SignalType = "technical" | "product" | "ecosystem" | "industry" | "community";

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
  heat_score: number | null;
  signal_type: SignalType | null;
  technical_overview: string | null;
  novelty_summary: string | null;
  heat_reasons: string[];
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
  analysis_depth: "brief" | "deep";
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

export interface RadarEdition {
  id: string;
  captured_at: string;
  finished_at: string | null;
  status: "running" | "complete" | "failed";
  article_count: number;
  source_results: Array<Record<string, unknown>>;
  progress: {
    stage: "queued" | "collecting" | "normalizing" | "analyzing" | "complete" | "failed";
    completed: number;
    total: number;
    message: string;
    current_source?: string | null;
  };
  error_summary: string | null;
}

export interface RadarEditionList {
  items: RadarEdition[];
}

export interface CleanupReport {
  keep_editions: number;
  keep_fetch_runs_per_source: number;
  keep_analysis_runs_per_article: number;
  blocked: boolean;
  running_editions: number;
  running_fetch_runs: number;
  running_analysis_runs: number;
  editions: number;
  articles: number;
  raw_items: number;
  fetch_runs: number;
  analysis_runs: number;
  authors: number;
  tags: number;
  event_clusters: number;
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

export type WritingFormat = "short_post" | "thread" | "article";

export interface HumanInput {
  core_take: string;
  personal_observation: string;
  disagreement: string;
}

export interface WritingAngle {
  id: "technical" | "industry" | "practitioner";
  label: string;
  thesis: string;
  signal: string;
  mechanism: string;
  change: string;
  tension: string;
  evidence: string[];
  counterargument: string;
  uncertainty: string;
  reader_gain: string;
  recommended_format: WritingFormat;
  value_score: number;
}

export interface WritingReviewIssue {
  category: "fact" | "generic" | "ai_tone" | "logic" | "voice" | "format";
  severity: "high" | "medium" | "low";
  quote: string;
  problem: string;
  suggestion: string;
}

export interface WritingReview {
  verdict: string;
  thesis_clarity: number;
  originality: number;
  technical_clarity: number;
  human_voice: number;
  issues: WritingReviewIssue[];
  strongest_line: string;
  cut_suggestions: string[];
}

export interface WritingProject {
  id: string;
  article_id: string;
  status: string;
  angle_options: WritingAngle[];
  selected_angle_id: string | null;
  output_format: WritingFormat;
  human_input: HumanInput;
  draft_content: string | null;
  review: WritingReview | null;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}
