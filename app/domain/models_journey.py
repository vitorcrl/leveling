"""
Contexto de dados para o digest semanal da jornada de usuário (MVP do bot).

Não confundir com DigestContext (app/domain/models_asset.py) — aquele é sobre
FIIs/alertas de mercado (Parte 2), este é sobre o progresso do usuário na
jornada financeira (dívida, reserva, caixinha, FIIs).
"""

from dataclasses import dataclass

from app.domain.models_user import User, UserDebt, UserEmergencyFund, UserGoal


@dataclass
class JourneyDigestContext:
    """Dados passados ao ClaudeJourneyNarrator para montar o digest semanal de 1 usuário."""

    user: User
    debt: UserDebt | None
    fund: UserEmergencyFund | None
    goal: UserGoal | None
    profile_summary: dict | None
