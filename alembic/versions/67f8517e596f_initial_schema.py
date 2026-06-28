"""initial schema

Revision ID: 67f8517e596f
Revises:
Create Date: 2026-06-28

Cria todas as tabelas do MVP:
  - FII (asset_snapshots, fii_portfolio, fii_trades, fii_proventos, fii_budget)
  - Usuário (users, user_goals, user_debts, user_portfolio, user_dividends)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "67f8517e596f"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # FII — tabelas herdadas do projeto original
    # -------------------------------------------------------------------------
    op.create_table(
        "asset_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("market", sa.String(5), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("dy_12m", sa.Float, nullable=False),
        sa.Column("pvp", sa.Float, nullable=False),
        sa.Column("vacancia", sa.Float, nullable=True),
        sa.Column("ltv", sa.Float, nullable=True),
        sa.Column("liquidez", sa.Float, nullable=False),
        sa.Column("ffo_per_share", sa.Float, nullable=True),
        sa.Column("price_ffo", sa.Float, nullable=True),
        sa.Column("debt_ebitda", sa.Float, nullable=True),
        sa.Column("occupancy", sa.Float, nullable=True),
        sa.Column("eps", sa.Float, nullable=True),
        sa.Column("book_value_per_share", sa.Float, nullable=True),
        sa.Column("roe", sa.Float, nullable=True),
        sa.Column("ev_ebitda", sa.Float, nullable=True),
        sa.Column("revenue_growth", sa.Float, nullable=True),
        sa.Column("net_margin", sa.Float, nullable=True),
        sa.Column("debt_equity", sa.Float, nullable=True),
        sa.Column("beta", sa.Float, nullable=True),
        sa.Column("payout_ratio", sa.Float, nullable=True),
        sa.Column("provento_anunciado", sa.Numeric(10, 4), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_asset_snapshots_ticker_date",
        "asset_snapshots",
        ["ticker", "date"],
        unique=True,
    )

    op.create_table(
        "fii_portfolio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(20), unique=True, nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("avg_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_invested", sa.Numeric(14, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "fii_trades",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_fii_trades_ticker_date", "fii_trades", ["ticker", "date"])

    op.create_table(
        "fii_proventos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("amount_per_share", sa.Numeric(10, 4), nullable=False),
        sa.Column("total_received", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_fii_proventos_ticker_date", "fii_proventos", ["ticker", "date"])

    op.create_table(
        "fii_budget",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("week_start", sa.Date, unique=True, nullable=False),
        sa.Column("base_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("reinvested_income", sa.Numeric(14, 2), nullable=False),
        sa.Column("carried_over", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # -------------------------------------------------------------------------
    # Usuário — tabelas novas do MVP de jornada financeira
    # -------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("stage", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("monthly_budget", sa.Numeric(10, 2), nullable=True),
        sa.Column("risk_profile", sa.String(20), nullable=True),
        sa.Column("onboarding_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_interaction_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"], unique=True)

    op.create_table(
        "user_goals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("goal_value_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("achieved_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_user_goals_user_id", "user_goals", ["user_id"])

    op.create_table(
        "user_debts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("initial_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("last_celebrated_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_user_debts_user_id", "user_debts", ["user_id"])

    op.create_table(
        "user_portfolio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("shares", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("user_id", "ticker", name="uq_user_portfolio_user_ticker"),
    )

    op.create_table(
        "user_dividends",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("received_date", sa.Date, nullable=False),
        sa.Column("amount_per_share", sa.Numeric(10, 4), nullable=False),
        sa.Column("shares_at_time", sa.Integer, nullable=False),
        sa.Column("total_received", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_user_dividends_user_id_date",
        "user_dividends",
        ["user_id", "received_date"],
    )


def downgrade() -> None:
    op.drop_table("user_dividends")
    op.drop_table("user_portfolio")
    op.drop_table("user_debts")
    op.drop_table("user_goals")
    op.drop_table("users")
    op.drop_table("fii_budget")
    op.drop_table("fii_proventos")
    op.drop_table("fii_trades")
    op.drop_table("fii_portfolio")
    op.drop_table("asset_snapshots")
