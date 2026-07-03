"""
Handlers de comandos do bot pós-onboarding.

/atualizar <valor>  — atualiza o saldo atual da dívida (stage 0)
                      se valor for 0, promove automaticamente para stage 1
/pausar             — suspende o digest semanal proativo (controle explícito do usuário)
/retomar            — reativa o digest semanal
callback: stage_check_sim / stage_check_nao — resposta ao botão inline de promoção 1→2
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.core.database import AsyncSessionFactory
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

_CALLBACK_SIM = "stage_check_sim"
_CALLBACK_NAO = "stage_check_nao"


def _parse_amount(text: str) -> Decimal | None:
    cleaned = text.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif re.match(r"^\d{1,3}(\.\d{3})+$", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
        return value if value >= 0 else None
    except InvalidOperation:
        return None


async def cmd_atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /atualizar <valor> — atualiza saldo da dívida."""
    chat_id = update.effective_user.id

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usa assim: /atualizar 3500\n"
            "Manda o saldo atual da sua dívida. Se quitou tudo, manda /atualizar 0"
        )
        return

    amount = _parse_amount(args[0])
    if amount is None:
        await update.message.reply_text(
            "Não entendi o valor. Tenta: /atualizar 3500 ou /atualizar 0"
        )
        return

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None or not user.onboarding_complete:
            await update.message.reply_text(
                "Você ainda não completou o onboarding. Manda /start para começar."
            )
            return

        if user.stage != 0:
            await update.message.reply_text(
                "O comando /atualizar é para quem está quitando dívidas (Estágio 0).\n"
                f"Você está no Estágio {user.stage}."
            )
            return

        debt = await repo.get_active_debt(user.id)
        if debt is None:
            await update.message.reply_text(
                "Não encontrei uma dívida ativa no seu perfil. "
                "Se precisar, manda /start para refazer o onboarding."
            )
            return

        if amount == 0:
            await repo.promote_stage(user.id, new_stage=1)
            await update.message.reply_text(
                "🎉 Parabéns! Você quitou a dívida!\n\n"
                "Você avançou para o *Estágio 1: Construindo a caixinha*.\n"
                "Agora o foco é acumular R$ 1.000 para partir para os FIIs!",
                parse_mode="Markdown",
            )
            logger.info("cmd_atualizar: chat_id=%s promoted to stage 1", chat_id)
            return

        await repo.update_debt_amount(user.id, amount)
        debt = await repo.get_active_debt(user.id)

        paid = max(debt.initial_amount - debt.current_amount, Decimal(0))
        pct = (paid / debt.initial_amount * 100) if debt.initial_amount else Decimal(0)
        pct_str = f"{pct:.1f}".replace(".", ",")

        def _fmt(v: Decimal) -> str:
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        await update.message.reply_text(
            f"✅ Saldo atualizado!\n\n"
            f"Dívida inicial: {_fmt(debt.initial_amount)}\n"
            f"Saldo atual: {_fmt(amount)}\n"
            f"Pago até agora: {pct_str}%\n\n"
            f"Continue assim! Quando chegar em 0, manda /atualizar 0 para avançar. 💪"
        )
        logger.info(
            "cmd_atualizar: chat_id=%s updated debt to %s (%.1f%% paid)",
            chat_id,
            amount,
            float(pct),
        )


async def cmd_pausar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /pausar — suspende o digest semanal proativo."""
    chat_id = update.effective_user.id

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None or not user.onboarding_complete:
            await update.message.reply_text(
                "Você ainda não completou o onboarding. Manda /start para começar."
            )
            return

        if user.paused:
            await update.message.reply_text("Seus envios já estão pausados. 👍")
            return

        await repo.set_paused(user.id, paused=True)
        await update.message.reply_text(
            "⏸️ Envios semanais pausados. Manda /retomar quando quiser voltar."
        )
        logger.info("cmd_pausar: chat_id=%s paused", chat_id)


async def cmd_retomar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /retomar — reativa o digest semanal proativo."""
    chat_id = update.effective_user.id

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None or not user.onboarding_complete:
            await update.message.reply_text(
                "Você ainda não completou o onboarding. Manda /start para começar."
            )
            return

        if not user.paused:
            await update.message.reply_text("Seus envios já estão ativos. 👍")
            return

        await repo.set_paused(user.id, paused=False)
        await update.message.reply_text(
            "▶️ Envios semanais retomados. Você volta a receber o digest toda segunda!"
        )
        logger.info("cmd_retomar: chat_id=%s resumed", chat_id)


async def callback_stage_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback dos botões inline de promoção stage 1→2."""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_user.id
    data = query.data

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None or user.stage != 1:
            await query.edit_message_text("Essa pergunta não é mais válida para o seu perfil.")
            return

        if data == _CALLBACK_SIM:
            await repo.promote_stage(user.id, new_stage=2)
            await query.edit_message_text(
                "🚀 Incrível! Você chegou no *Estágio 2: Investindo em FIIs*!\n\n"
                "A partir de agora você recebe análise semanal da watchlist de FIIs "
                "e sugestões de aporte baseadas no seu perfil.\n\n"
                "Vamos crescer esse patrimônio! 📈",
                parse_mode="Markdown",
            )
            logger.info("callback_stage_check: chat_id=%s promoted to stage 2", chat_id)

        elif data == _CALLBACK_NAO:
            await query.edit_message_text(
                "Tranquilo! Continue guardando — quando tiver R$ 1.000 me avisa. 💰\n\n"
                "Vou perguntar de novo semana que vem."
            )
            logger.info("callback_stage_check: chat_id=%s stays at stage 1", chat_id)


def build_command_handlers() -> list:
    return [
        CommandHandler("atualizar", cmd_atualizar),
        CommandHandler("pausar", cmd_pausar),
        CommandHandler("retomar", cmd_retomar),
        CallbackQueryHandler(callback_stage_check, pattern=f"^({_CALLBACK_SIM}|{_CALLBACK_NAO})$"),
    ]
