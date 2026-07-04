"""add emergency fund stage (0.5)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_emergency_fund",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("target_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_user_emergency_fund_user_id",
        "user_emergency_fund",
        ["user_id"],
    )

    op.add_column(
        "users",
        sa.Column("monthly_essential_expense", sa.Numeric(10, 2), nullable=True),
    )

    # Renumeração de stage: abre espaço para o novo stage=1 (reserva de
    # emergência) entre dívida (0) e caixinha (antigo 1). CASE numa única
    # query evita colisão de ordem (2→3 e 1→2 aplicados atomicamente).
    op.execute(
        """
        UPDATE users
        SET stage = CASE
            WHEN stage = 2 THEN 3
            WHEN stage = 1 THEN 2
            ELSE stage
        END
        """
    )


def downgrade() -> None:
    # stage=1 (reserva de emergência) não existia antes desta migration —
    # rebaixa para 0 (dívida) já que o usuário ainda não tinha caixinha formada.
    op.execute(
        """
        UPDATE users
        SET stage = CASE
            WHEN stage = 3 THEN 2
            WHEN stage = 2 THEN 1
            WHEN stage = 1 THEN 0
            ELSE stage
        END
        """
    )

    op.drop_column("users", "monthly_essential_expense")

    op.drop_index("ix_user_emergency_fund_user_id", table_name="user_emergency_fund")
    op.drop_table("user_emergency_fund")
