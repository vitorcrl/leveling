"""add stage_check_sent_at to users

Revision ID: a1b2c3d4e5f6
Revises: 67f8517e596f
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "67f8517e596f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("stage_check_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "stage_check_sent_at")
