"""Add persistent manual capture progress.

Revision ID: 0007_radar_edition_progress
Revises: 0006_radar_editions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_radar_edition_progress"
down_revision: str | None = "0006_radar_editions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "radar_editions",
        sa.Column(
            "progress",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE radar_editions
        SET progress = jsonb_build_object(
            'stage', CASE WHEN status = 'complete' THEN 'complete' ELSE status::text END,
            'completed', article_count,
            'total', article_count,
            'message', CASE
                WHEN status = 'complete' THEN '历史期次已完成'
                ELSE '历史期次'
            END
        )
        """
    )


def downgrade() -> None:
    op.drop_column("radar_editions", "progress")
