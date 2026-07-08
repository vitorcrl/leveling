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

from app.domain.fii_catalog import get_fii_info
from app.domain.models_user import User
from app.repositories.user_repository import UserRepository

_DIVIDEND_LOOKBACK_DAYS = 90

# Rótulo humano para o stage interno — nunca mostrar só o número cru pra IA.
_STAGE_LABELS = {
    0: "quitando dívida",
    1: "reserva de emergência",
    2: "construindo caixinha rumo à 1ª cota de FII",
    3: "investindo em FIIs",
}

# Pergunta em linguagem natural para cada step do onboarding (ver
# app/bot/onboarding.py, _record_event) — os nomes internos (essential_expense,
# has_portfolio etc.) são shorthand de código, não texto pronto para IA.
_STEP_LABELS = {
    "debt": "Tem dívida com juros altos?",
    "debt_amount": "Valor total da dívida",
    "essential_expense": "Gasto mensal essencial",
    "budget": "Quanto consegue guardar/pagar por mês",
    "savings": "Já tinha dinheiro guardado no início?",
    "goal": "Meta escolhida",
    "goal_value": "Custo mensal da meta",
    "profile": "Perfil de risco escolhido",
    "has_portfolio": "Já tinha FII na carteira?",
    "portfolio": "Tickers informados",
    "portfolio_shares": "Quantidade de cotas por ticker",
    "knows_fii": "Já sabia o que é um FII?",
}

# Callback_data bruto do Telegram (ver onboarding.py) traduzido para texto —
# sem isso, o dossiê vazaria strings internas tipo "onb_portfolio_sim".
_RAW_VALUE_LABELS = {
    "onb_portfolio_sim": "sim",
    "onb_portfolio_nao": "não",
    "onb_knows_fii_sim": "sim",
    "onb_knows_fii_nao": "não",
}


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "não informado"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _stage_label(stage: int) -> str:
    return _STAGE_LABELS.get(stage, f"estágio {stage}")


def _step_label(step: str) -> str:
    return _STEP_LABELS.get(step, step)


def _raw_value_label(raw_value: str | None) -> str:
    if raw_value is None:
        return "-"
    return _RAW_VALUE_LABELS.get(raw_value, raw_value)


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
        f"Estágio atual: {_stage_label(user.stage)}",
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
        info = get_fii_info(position.ticker)
        if info is not None:
            lines.append(
                f"- {position.ticker} ({info.nome}, tipo {info.tipo_label}): "
                f"{position.shares} cotas"
            )
        else:
            lines.append(f"- {position.ticker} (tipo não catalogado): {position.shares} cotas")
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
        step = _step_label(event.step)
        raw_value = _raw_value_label(event.raw_value)
        if event.response_type == "answered":
            lines.append(f"- {step}: {raw_value}")
        elif event.response_type == "skipped":
            lines.append(f"- {step}: usuário pulou essa pergunta")
        elif event.response_type == "dont_know":
            lines.append(f"- {step}: usuário respondeu 'não sei'")
        else:
            lines.append(f"- {step}: {event.response_type} (valor: {raw_value})")
    return "\n".join(lines)
