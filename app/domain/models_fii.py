# Modelos SQLAlchemy para as tabelas do módulo de FIIs.

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID

from app.domain.base import Base

# Atalho para preencher created_at/updated_at sempre em UTC sem fuso.
# O replace(tzinfo=None) é necessário porque o PostgreSQL espera
# um datetime "naive" quando a coluna não tem timezone.
_utc_now = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


class AssetSnapshotORM(Base):
    """
    Guarda o snapshot diário de cada ativo (FII, REIT ou ação).
    Um registro por (ticker, date) — o índice composto abaixo garante
    buscas rápidas ao calcular os deltas vs semana anterior.
    """

    __tablename__ = "asset_snapshots"
    __table_args__ = (
        # UniqueConstraint garante que só existe um snapshot por (ticker, date).
        # Sem isso, dois fetches no mesmo dia gerariam dois registros — os deltas
        # ficariam errados porque o pipeline pegaria o primeiro ao comparar.
        # O índice composto junto otimiza as queries de busca por range de datas.
        Index("ix_asset_snapshots_ticker_date", "ticker", "date", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(20), nullable=False)
    market = Column(String(5), nullable=False)    # "BR" ou "US"
    date = Column(Date, nullable=False)
    price = Column(Numeric(12, 4), nullable=False)

    # Indicadores fundamentalistas — FIIs BR e REITs US
    dy_12m = Column(Float, nullable=False)        # dividend yield 12m em %
    pvp = Column(Float, nullable=False)           # preço / valor patrimonial
    vacancia = Column(Float, nullable=True)       # % vacância (tijolo) ou None
    ltv = Column(Float, nullable=True)            # loan-to-value % (papel) ou None
    liquidez = Column(Float, nullable=False)      # volume médio diário em R$

    # Indicadores de REITs US — None para FIIs
    ffo_per_share = Column(Float, nullable=True)  # funds from operations por cota
    price_ffo = Column(Float, nullable=True)      # price / FFO (equivalente ao P/L)
    debt_ebitda = Column(Float, nullable=True)    # dívida líquida / EBITDA
    occupancy = Column(Float, nullable=True)      # taxa de ocupação em %

    # Indicadores de ações — None para FIIs e REITs
    eps = Column(Float, nullable=True)                  # lucro por ação
    book_value_per_share = Column(Float, nullable=True) # valor patrimonial por ação
    roe = Column(Float, nullable=True)                  # return on equity em %
    ev_ebitda = Column(Float, nullable=True)            # enterprise value / EBITDA
    revenue_growth = Column(Float, nullable=True)       # crescimento de receita YoY %
    net_margin = Column(Float, nullable=True)           # margem líquida em %
    debt_equity = Column(Float, nullable=True)          # dívida / patrimônio líquido
    beta = Column(Float, nullable=True)                 # volatilidade vs índice
    payout_ratio = Column(Float, nullable=True)         # % do lucro distribuído

    # Deltas NÃO são salvos: calculados em runtime (hoje - semana_passada).
    # Guardar derivações seria redundância — o dado bruto já está aqui.

    # None se nenhum provento foi anunciado neste dia
    provento_anunciado = Column(Numeric(10, 4), nullable=True)

    created_at = Column(DateTime, default=_utc_now, nullable=False)


class FIIPortfolio(Base):
    """
    Posição atual da carteira para cada ticker.
    Um registro por ticker (unique), atualizado a cada compra.
    O preço médio é recalculado pelo pipeline de alocação.
    """

    __tablename__ = "fii_portfolio"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(20), unique=True, nullable=False)
    shares = Column(Integer, nullable=False, default=0)         # cotas em carteira
    avg_price = Column(Numeric(12, 4), nullable=False, default=0)   # preço médio de compra
    total_invested = Column(Numeric(14, 2), nullable=False, default=0)  # valor total aportado

    # onupdate garante que o campo é atualizado automaticamente em qualquer UPDATE
    updated_at = Column(
        DateTime,
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )


class FIITrade(Base):
    """
    Histórico imutável de cada compra executada.
    Nunca é alterado — serve de auditoria e para recalcular o preço médio.
    """

    __tablename__ = "fii_trades"
    __table_args__ = (
        Index("ix_fii_trades_ticker_date", "ticker", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    shares = Column(Integer, nullable=False)                  # cotas compradas
    price = Column(Numeric(12, 4), nullable=False)            # preço por cota
    total_amount = Column(Numeric(14, 2), nullable=False)     # valor total pago

    created_at = Column(DateTime, default=_utc_now, nullable=False)


class FIIProvento(Base):
    """
    Proventos (dividendos) recebidos por ticker.
    O pipeline de alocação soma os proventos dos últimos 7 dias
    para reinvestir no orçamento semanal.
    """

    __tablename__ = "fii_proventos"
    __table_args__ = (
        Index("ix_fii_proventos_ticker_date", "ticker", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    amount_per_share = Column(Numeric(10, 4), nullable=False)  # R$ por cota
    total_received = Column(Numeric(14, 2), nullable=False)    # total = cotas × valor_por_cota

    created_at = Column(DateTime, default=_utc_now, nullable=False)


class FIIBudget(Base):
    """
    Orçamento semanal de compras. Um registro por semana (week_start = segunda-feira).
    O total é calculado como: orcamento_base + proventos_7d + sobra_semana_anterior.
    A sobra acumula quando o preço das cotas não divide exatamente o orçamento.
    """

    __tablename__ = "fii_budget"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    week_start = Column(Date, unique=True, nullable=False)        # segunda-feira da semana
    base_budget = Column(Numeric(14, 2), nullable=False)          # aporte fixo configurado
    reinvested_income = Column(Numeric(14, 2), nullable=False, default=0)  # proventos dos 7 dias
    carried_over = Column(Numeric(14, 2), nullable=False, default=0)       # sobra acumulada
    total = Column(Numeric(14, 2), nullable=False)                # base + proventos + sobra

    created_at = Column(DateTime, default=_utc_now, nullable=False)
