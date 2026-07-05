# Narrator do digest semanal da jornada de usuário (MVP do bot) — implementa NarratorPort.
#
# Não confundir com ClaudeHaikuNarrator (Parte 2, FIIs/alertas de mercado).
#
# Filosofia de custo: o profile_summary (caro de pensar) só é regenerado em
# eventos específicos (ver profile_service.py) — mas o texto do digest em si
# (barato, curto) pode ser gerado toda semana quando há um perfil disponível.
# Sem perfil (None) ou se a API falhar, cai no fallback determinístico
# (_build_stageN_message), sem gastar tokens.

import logging

import anthropic

from app.core.config import get_settings
from app.domain.models_journey import JourneyDigestContext

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 400

_SYSTEM_PROMPT = """\
Você é o Leveling — um bot que acompanha jornadas financeiras, desde quitar \
dívidas até investir em FIIs. Seu tom nunca cobra, nunca julga, é direto e \
motivacional, sem jargão financeiro desnecessário.

Você recebe o progresso determinístico da semana de um usuário (números já \
calculados) e um perfil interpretado sobre como essa pessoa prefere ser \
abordada. Reescreva a mensagem semanal incorporando o tom sugerido pelo \
perfil, mantendo todos os números e fatos do conteúdo determinístico — não \
invente valores novos, apenas ajuste tom e ênfase.

Responda só com o texto final da mensagem (pode usar Markdown do Telegram).
"""


class ClaudeJourneyNarrator:
    """
    Narrator que personaliza o digest semanal usando o profile_summary do usuário.
    Implementa NarratorPort. Fallback: build_deterministic_message quando não há
    perfil ou a API falha.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            key = self._api_key or get_settings().ANTHROPIC_API_KEY
            self._client = anthropic.AsyncAnthropic(api_key=key)
        return self._client

    async def narrate(self, context: JourneyDigestContext) -> str:
        deterministic_message = _build_deterministic_message(context)

        if context.profile_summary is None:
            logger.info(
                "ClaudeJourneyNarrator: no profile_summary for chat_id=%s — using deterministic message",
                context.user.telegram_chat_id,
            )
            return deterministic_message

        try:
            client = self._get_client()
            user_prompt = (
                f"Conteúdo determinístico da semana:\n{deterministic_message}\n\n"
                f"Perfil interpretado do usuário:\n{context.profile_summary}"
            )
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            logger.exception(
                "ClaudeJourneyNarrator: failed to personalize digest for chat_id=%s — "
                "falling back to deterministic message",
                context.user.telegram_chat_id,
            )
            return deterministic_message


def _build_deterministic_message(context: JourneyDigestContext) -> str:
    """Delega para as funções _build_stageN_message já existentes em weekly_runner.py."""
    from app.scheduler import weekly_runner

    user = context.user
    if user.stage == 0:
        return weekly_runner._build_stage0_message(user, context.debt, context.goal)
    if user.stage == 1:
        return weekly_runner._build_stage1_message(user, context.fund, context.goal)
    if user.stage == 2:
        return weekly_runner._build_stage2_message(user, context.goal)
    if user.stage == 3:
        return weekly_runner._build_stage3_message(user, context.goal)

    logger.warning(
        "ClaudeJourneyNarrator: unknown stage=%s for chat_id=%s", user.stage, user.telegram_chat_id
    )
    return "Continue acompanhando sua jornada — em breve mais novidades!"
