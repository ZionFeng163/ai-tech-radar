"""Add bounded claim verification and final writing fields.

Revision ID: 0012_verified_writing_claims
Revises: 0011_retire_arxiv
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_verified_writing_claims"
down_revision: str | None = "0011_retire_arxiv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "writing_projects",
        sa.Column(
            "claim_ledger",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "writing_projects",
        sa.Column(
            "verification",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("writing_projects", sa.Column("final_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("writing_projects", "final_content")
    op.drop_column("writing_projects", "verification")
    op.drop_column("writing_projects", "claim_ledger")
