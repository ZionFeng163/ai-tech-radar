from enum import StrEnum


class SourceKind(StrEnum):
    ARXIV = "arxiv"
    GITHUB_RELEASES = "github_releases"
    HUGGING_FACE = "hugging_face"
    RSS = "rss"
    BLOG = "blog"
    OTHER = "other"


class ArticleKind(StrEnum):
    PAPER = "paper"
    CODE_REPOSITORY = "code_repository"
    RELEASE = "release"
    MODEL = "model"
    DATASET = "dataset"
    BLOG_POST = "blog_post"
    NEWS = "news"


class FetchRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
