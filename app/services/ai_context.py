"""
Monta o dossiê textual completo de um usuário — tudo que o Leveling sabe
sobre ele — para servir de contexto a qualquer chamada de IA (geração de
perfil em profile_service.py, e qualquer consumidor futuro).

Centralizado aqui em vez de dentro de profile_service.py porque o mesmo
dossiê pode ser útil para mais de uma chamada de IA no futuro — não é
específico da geração de perfil.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.domain.models_user import User
from app.repositories.user_repository import UserRepository

_DIVIDEND_LOOKBACK_DAYS = 90


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "não informado"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def build_user_information(repo: UserRepository, user: User) -> str:
    """
    Busca dívida, reserva, portfólio, dividendos recentes, meta ativa e
    eventos de onboarding do banco, e monta um texto único pronto para
    entrar no prompt de uma chamada de IA.
    """
    debt = await repo.get_active_debt(user.id)
    fund = await repo.get_active_emergency_fund(user.id)
    goal = await repo.get_active_goal(user.id)
    portfolio = await repo.get_portfolio(user.id)
    since = date.today() - timedelta(days=_DIVIDEND_LOOKBACK_DAYS)
    dividends = await repo.get_recent_dividends(user.id, since=since)
    events = await repo.get_onboarding_events(user.id)

    sections = [
        _build_profile_section(user),
        _build_goal_section(goal),
        _build_debt_section(debt),
        _build_emergency_fund_section(fund),
        _build_portfolio_section(portfolio),
        _build_dividends_section(dividends),
        _build_events_section(events),
    ]
    return "\n\n".join(sections)


def _build_profile_section(user: User) -> str:
    lines = [
        "=== Perfil financeiro ===",
        f"Estágio atual: {user.stage}",
        f"Aporte mensal: {_fmt(user.monthly_budget)}",
        f"Perfil de risco: {user.risk_profile or 'não informado'}",
        f"Gasto essencial informado: {_fmt(user.monthly_essential_expense)}",
    ]
    return "\n".join(lines)


def _build_goal_section(goal) -> str:
    if goal is None:
        return "=== Meta ===\nSem meta ativa."
    return f"=== Meta ===\nMeta ativa: {goal.name} ({_fmt(goal.goal_value_monthly)}/mês)"


def _build_debt_section(debt) -> str:
    if debt is None:
        return "=== Dívida ===\nSem dívida ativa."
    paid = max(debt.initial_amount - debt.current_amount, Decimal(0))
    return (
        "=== Dívida ===\n"
        f"Dívida inicial: {_fmt(debt.initial_amount)}\n"
        f"Saldo atual: {_fmt(debt.current_amount)}\n"
        f"Pago até agora: {_fmt(paid)}"
    )


def _build_emergency_fund_section(fund) -> str:
    if fund is None:
        return "=== Reserva de emergência ===\nSem reserva ativa (estágio pulado ou já concluído)."
    return (
        "=== Reserva de emergência ===\n"
        f"Guardado: {_fmt(fund.current_amount)} / {_fmt(fund.target_amount)}"
    )


def _build_portfolio_section(portfolio: list) -> str:
    if not portfolio:
        return "=== Carteira de FIIs ===\nSem FIIs na carteira."
    lines = ["=== Carteira de FIIs ==="]
    for position in portfolio:
        lines.append(f"- {position.ticker}: {position.shares} cotas")
    return "\n".join(lines)


def _build_dividends_section(dividends: list) -> str:
    if not dividends:
        return f"=== Dividendos recebidos (últimos {_DIVIDEND_LOOKBACK_DAYS} dias) ===\nNenhum dividendo informado no período."
    lines = [f"=== Dividendos recebidos (últimos {_DIVIDEND_LOOKBACK_DAYS} dias) ==="]
    for dividend in dividends:
        lines.append(
            f"- {dividend.ticker}: {_fmt(dividend.amount_per_share)}/cota em "
            f"{dividend.received_date.isoformat()} (total: {_fmt(dividend.total_received)})"
        )
    return "\n".join(lines)


def _build_events_section(events: list) -> str:
    if not events:
        return "=== Respostas do onboarding ===\nSem eventos registrados."
    lines = ["=== Respostas do onboarding ==="]
    for event in events:
        lines.append(f"- {event.step}: {event.response_type} (valor: {event.raw_value or '-'})")
    return "\n".join(lines)
