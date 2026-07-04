import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.domain.base import Base

_utc_now = lambda: datetime.utcnow()  # noqa: E731


class User(Base):
    """
    Um registro por usuário do bot. Chave de roteamento é telegram_chat_id —
    é o que o Telegram nos envia em cada update e o que passamos para o adapter.

    stage: 0 = quitando dívida, 1 = reserva de emergência (Estágio 0.5),
        2 = acumulando na caixinha rumo ao 1º FII, 3 = investindo em FIIs.
    monthly_budget: aporte mensal informado no onboarding (R$).
    monthly_essential_expense: gasto mensal essencial autodeclarado (aluguel,
        contas, mercado) — usado para calcular a meta da reserva de emergência
        (5x esse valor). NULL significa que o usuário pulou a pergunta ou
        respondeu "não sei" no onboarding.
    risk_profile: 'conservador' ou 'moderado' — determina quais FIIs sugerir.
    last_interaction_at: atualizado a cada mensagem recebida do usuário,
        usado pela lógica de ausência (semana 2 → lembrete leve, semana 3+ → parar proativo).
    onboarding_complete: False até o ConversationHandler terminar todos os passos.
    paused: controle explícito do usuário via /pausar e /retomar — o digest semanal
        é enviado a todo usuário com onboarding completo e paused=False, independente
        de última interação (decisão de produto de 2026-07-02: sem pausa automática
        por ausência).
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    stage = Column(SmallInteger, nullable=False, default=0)
    monthly_budget = Column(Numeric(10, 2), nullable=True)
    monthly_essential_expense = Column(Numeric(10, 2), nullable=True)  # gasto mensal essencial autodeclarado
    risk_profile = Column(String(20), nullable=True)        # 'conservador' | 'moderado'
    onboarding_complete = Column(Boolean, nullable=False, default=False)
    paused = Column(Boolean, nullable=False, default=False)
    savings_amount = Column(Numeric(12, 2), nullable=True)   # dinheiro guardado declarado no onboarding
    last_interaction_at = Column(DateTime, nullable=True)
    stage_check_sent_at = Column(DateTime, nullable=True)  # última vez que perguntamos sobre promoção de stage
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class UserGoal(Base):
    """
    Meta financeira escolhida no onboarding — ex: "Monster R$12/mês".

    Um usuário tem uma meta ativa por vez (MVP). achieved_at preenchido
    quando progresso >= 100% — bot celebra e oferece escolher a próxima.
    goal_value_monthly: custo mensal da meta em R$ (ex: 12.00 para o Monster).
    """

    __tablename__ = "user_goals"
    __table_args__ = (
        Index("ix_user_goals_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)               # ex: "Monster", "Academia"
    goal_value_monthly = Column(Numeric(10, 2), nullable=False)  # R$/mês necessários
    achieved_at = Column(DateTime, nullable=True)            # preenchido quando atingida
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class UserDebt(Base):
    """
    Dívida autodeclarada — usada no Estágio 0.

    Valores são sempre informados pelo usuário, nunca calculados automaticamente.
    last_celebrated_amount: último múltiplo de R$100 que foi celebrado —
        evita reenviar celebração se o usuário atualizar o saldo mais de uma vez
        na mesma semana sem quitar outro R$100.
    """

    __tablename__ = "user_debts"
    __table_args__ = (
        Index("ix_user_debts_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    initial_amount = Column(Numeric(12, 2), nullable=False)  # dívida declarada no início
    current_amount = Column(Numeric(12, 2), nullable=False)  # saldo atualizado pelo usuário
    last_celebrated_amount = Column(Numeric(12, 2), nullable=True)  # último valor celebrado
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class UserPortfolio(Base):
    """
    Posição em FIIs informada pelo usuário — um registro por (user, ticker).

    Preenchido no onboarding (quem já tem FIIs) ou atualizado quando o usuário
    reporta uma compra nova. shares e avg_price são autodeclarados — não há
    integração com corretora no MVP.
    """

    __tablename__ = "user_portfolio"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_user_portfolio_user_ticker"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    shares = Column(Integer, nullable=False, default=0)
    avg_price = Column(Numeric(12, 4), nullable=True)        # pode ser omitido no onboarding
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class UserDividend(Base):
    """
    Dividendo informado manualmente pelo usuário — Estágio 2.

    O usuário envia "MXRF11 R$0,09" e o bot registra aqui.
    amount_per_share × shares_at_time = total_received.
    shares_at_time é registrado no momento do report (a posição pode mudar depois).
    """

    __tablename__ = "user_dividends"
    __table_args__ = (
        Index("ix_user_dividends_user_id_date", "user_id", "received_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    received_date = Column(Date, nullable=False)
    amount_per_share = Column(Numeric(10, 4), nullable=False)  # R$/cota informado
    shares_at_time = Column(Integer, nullable=False)            # cotas na carteira no momento
    total_received = Column(Numeric(12, 2), nullable=False)     # amount_per_share × shares
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class UserEmergencyFund(Base):
    """
    Reserva de emergência autodeclarada — usada no Estágio 0.5 (stage=1).

    target_amount = 5x monthly_essential_expense, calculado no onboarding
    (ou quando o usuário informa o gasto mensal depois, via mensagem livre).
    Valores são sempre informados pelo usuário — mesma filosofia de
    UserDebt: sem integração bancária, sem prova.
    """

    __tablename__ = "user_emergency_fund"
    __table_args__ = (
        Index("ix_user_emergency_fund_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_amount = Column(Numeric(12, 2), nullable=False)
    current_amount = Column(Numeric(12, 2), nullable=False, default=0)
    completed_at = Column(DateTime, nullable=True)  # preenchido quando current >= target
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)
