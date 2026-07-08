"""
Geração do perfil de IA que personaliza o digest semanal (ver ClaudeJourneyNarrator).

Filosofia de custo: o perfil NÃO é regenerado a cada digest — só nos eventos
que indicam uma virada real na jornada do usuário (promoção de stage, meta
conquistada). A chamada nunca bloqueia o fluxo que a disparou: se falhar, o
perfil fica NULL e o narrator cai no fallback estático (_build_stageN_message).
"""

import json
import logging

import anthropic

from app.core.config import get_settings
from app.domain.models_user import User
from app.repositories.user_repository import UserRepository
from app.services.ai_context import build_user_information

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 512

_SYSTEM_PROMPT = """\
Você analisa as respostas de onboarding de um usuário do Leveling, um bot que \
acompanha jornadas financeiras (de quitar dívida até investir em FIIs), e \
sintetiza um perfil interpretado para personalizar mensagens futuras.

Preste atenção especial em quais perguntas o usuário pulou ou respondeu "não \
sei" — isso é um sinal de comportamento (ex: alguém que evita números pode \
preferir mensagens menos numéricas e mais motivacionais).

Responda APENAS com um JSON válido, sem texto antes ou depois, no formato:
{"tom_sugerido": "...", "pontos_de_atencao": ["..."], "motivadores": ["..."], "resumo": "..."}
"""


class _LazyClient:
    """Lazy init do cliente Anthropic — evita import-time de Settings em testes."""

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    def get(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=get_settings().ANTHROPIC_API_KEY)
        return self._client


_lazy_client = _LazyClient()


def _build_user_prompt(user: User, goal: UserGoal | None, events: list[OnboardingEvent]) -> str:
    lines = [
        f"Stage atual: {user.stage}",
        f"Aporte mensal: {user.monthly_budget}",
        f"Perfil de risco: {user.risk_profile or 'não informado'}",
        f"Gasto essencial informado: {user.monthly_essential_expense or 'não informado'}",
    ]
    if goal:
        lines.append(f"Meta ativa: {goal.name} (R$ {goal.goal_value_monthly}/mês)")

    lines.append("\nRespostas do onboarding:")
    for event in events:
        lines.append(f"- {event.step}: {event.response_type} (valor: {event.raw_value or '-'})")

    return "\n".join(lines)


async def generate_profile_summary(
    user: User,
    goal: UserGoal | None,
    events: list[OnboardingEvent],
    client: anthropic.AsyncAnthropic | None = None,
) -> dict | None:
    """
    Chama Claude para sintetizar o perfil. Retorna None (nunca propaga exceção)
    se a chamada falhar ou a resposta não for um JSON válido.
    """
    try:
        active_client = client or _lazy_client.get()
        user_prompt = _build_user_prompt(user, goal, events)

        response = await active_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        return json.loads(text)
    except Exception:
        logger.exception(
            "profile_service: failed to generate profile summary for user_id=%s", user.id
        )
        return None


async def generate_and_store_profile(user_id) -> None:
    """
    Ponto de entrada disparado como tarefa em background (asyncio.create_task) —
    nunca aguardado pelo fluxo que a chamou (onboarding, promoção de stage).
    Lê o estado atual do usuário do banco, gera o perfil e persiste; se
    qualquer etapa falhar, apenas loga — user_profile_summary permanece NULL.
    """
    from app.core.database import AsyncSessionFactory
    from app.repositories.user_repository import UserRepository

    try:
        async with AsyncSessionFactory() as session:
            repo = UserRepository(session)
            result = await session.get(User, user_id)
            if result is None:
                logger.warning("profile_service: user_id=%s not found — skipping", user_id)
                return

            goal = await repo.get_active_goal(user_id)
            events = await repo.get_onboarding_events(user_id)

            summary = await generate_profile_summary(result, goal, events)
            await repo.update_profile_summary(user_id, summary)
    except Exception:
        logger.exception(
            "profile_service: unexpected error generating profile for user_id=%s", user_id
        )
