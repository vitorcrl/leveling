"""add digest_weekday, onboarding_events, user_profile_summary

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("digest_weekday", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("user_profile_summary", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "onboarding_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("step", sa.String(40), nullable=False),
        sa.Column("response_type", sa.String(20), nullable=False),
        sa.Column("raw_value", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_onboarding_events_user_id",
        "onboarding_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_events_user_id", table_name="onboarding_events")
    op.drop_table("onboarding_events")

    op.drop_column("users", "user_profile_summary")
    op.drop_column("users", "digest_weekday")
