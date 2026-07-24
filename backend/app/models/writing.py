from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.article import Article


class WritingProject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded writing workspace per radar article.

    Phase one deliberately stores only the current draft and review instead of an
    unbounded revision history. Regeneration replaces those fields.
    """

    __tablename__ = "writing_projects"
    __table_args__ = (UniqueConstraint("article_id", name="uq_writing_projects_article_id"),)

    article_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="new", nullable=False)
    angle_options: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    selected_angle_id: Mapped[str | None] = mapped_column(String(50))
    output_format: Mapped[str] = mapped_column(String(30), default="thread", nullable=False)
    human_input: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    draft_content: Mapped[str | None] = mapped_column(Text)
    review: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    error_summary: Mapped[str | None] = mapped_column(Text)

    article: Mapped[Article] = relationship(back_populates="writing_project")
