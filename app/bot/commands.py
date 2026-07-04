"""
Handlers de comandos do bot pós-onboarding.

stage interno: 0=dívida, 1=reserva de emergência (Estágio 0.5), 2=caixinha, 3=FIIs.

/atualizar          — conversa guiada: pergunta se foi pagamento de dívida (stage 0)
                      ou dinheiro guardado para investir (stage 2), depois o valor.
                      Quitar a dívida promove automaticamente para stage 1 (reserva,
                      se o usuário informou gasto essencial) ou stage 2 (caixinha).
/reserva <valor>    — atualiza a reserva de emergência (stage 1). Ao bater a meta
                      (5x gasto essencial), promove para stage 2 (caixinha).
/pausar             — suspende o digest semanal proativo (controle explícito do usuário)
/retomar            — reativa o digest semanal
callback: stage_check_sim / stage_check_nao — resposta ao botão inline de promoção 2→3
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.onboarding import CALLBACK_COMECAR_AGORA
from app.core.database import AsyncSessionFactory
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

_CALLBACK_SIM = "stage_check_sim"
_CALLBACK_NAO = "stage_check_nao"

_CALLBACK_ATUALIZAR_DIVIDA = "atualizar_divida"
_CALLBACK_ATUALIZAR_SAVINGS = "atualizar_savings"

ASK_ATUALIZAR_TIPO, ASK_ATUALIZAR_VALOR = range(2)


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


def _fmt_reais(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# stage interno (0/1/2/3) -> rótulo de produto exibido ao usuário (0/0.5/1/2)
_STAGE_LABELS = {0: "0", 1: "0.5", 2: "1", 3: "2"}


def _stage_label(stage: int) -> str:
    return _STAGE_LABELS.get(stage, str(stage))


async def cmd_atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point de /atualizar — pergunta se foi pagamento de dívida ou dinheiro guardado."""
    chat_id = update.effective_user.id

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

    if user is None or not user.onboarding_complete:
        await update.message.reply_text(
            "Você ainda não completou o onboarding. Manda /start para começar."
        )
        return ConversationHandler.END

    if user.stage not in (0, 2):
        await update.message.reply_text(
            "O comando /atualizar é para quem está no Estágio 0 (dívida) "
            "ou Estágio 1 (construindo caixinha rumo ao 1º FII).\n"
            f"Você está no Estágio {_stage_label(user.stage)}."
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Paguei dívida", callback_data=_CALLBACK_ATUALIZAR_DIVIDA),
        InlineKeyboardButton("💰 Guardei p/ investir", callback_data=_CALLBACK_ATUALIZAR_SAVINGS),
    ]])
    await update.message.reply_text(
        "Você conseguiu quitar parte da dívida ou guardou dinheiro para investir?",
        reply_markup=keyboard,
    )
    return ASK_ATUALIZAR_TIPO


async def ask_atualizar_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_user.id
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

    if query.data == _CALLBACK_ATUALIZAR_DIVIDA:
        if user is None or user.stage != 0:
            await query.edit_message_text(
                "Esse fluxo é para quem está no Estágio 0 (dívida). "
                "Seu perfil já não está mais nesse estágio."
            )
            return ConversationHandler.END
        context.user_data["atualizar_tipo"] = "divida"
        await query.edit_message_text(
            "Quanto você pagou dessa vez?\nManda só o número. Ex: 200"
        )
    else:
        if user is None or user.stage != 2:
            await query.edit_message_text(
                "Esse fluxo é para quem está no Estágio 1 (caixinha). "
                "Seu perfil já não está mais nesse estágio."
            )
            return ConversationHandler.END
        context.user_data["atualizar_tipo"] = "savings"
        await query.edit_message_text(
            "Quanto você guardou dessa vez?\nManda só o número. Ex: 100"
        )

    return ASK_ATUALIZAR_VALOR


async def ask_atualizar_valor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_user.id
    amount = _parse_amount(update.message.text)

    if amount is None:
        await update.message.reply_text("Não entendi o valor. Manda só o número. Ex: 200")
        return ASK_ATUALIZAR_VALOR

    tipo = context.user_data.get("atualizar_tipo")

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None:
            await update.message.reply_text(
                "Você ainda não completou o onboarding. Manda /start para começar."
            )
            return ConversationHandler.END

        if tipo == "divida":
            debt = await repo.add_debt_payment(user.id, amount)
            if debt is None:
                await update.message.reply_text(
                    "Não encontrei uma dívida ativa no seu perfil. "
                    "Se precisar, manda /start para refazer o onboarding."
                )
                return ConversationHandler.END

            if debt.current_amount <= 0:
                if user.monthly_essential_expense is not None:
                    target_amount = user.monthly_essential_expense * 5
                    await repo.promote_to_emergency_fund(user.id, target_amount)
                    promotion_text = (
                        "🎉 Parabéns! Você quitou a dívida!\n\n"
                        "Você avançou para o *Estágio 0.5: Reserva de emergência*.\n"
                        f"Sua meta: {_fmt_reais(target_amount)} "
                        "(5x seu gasto essencial). Manda /reserva <valor> conforme for guardando!"
                    )
                    new_stage = 1
                else:
                    await repo.promote_stage(user.id, new_stage=2)
                    promotion_text = (
                        "🎉 Parabéns! Você quitou a dívida!\n\n"
                        "Você avançou para o *Estágio 1: Construindo a caixinha*.\n"
                        "Agora o foco é acumular capital para partir para os FIIs!"
                    )
                    new_stage = 2
                await update.message.reply_text(promotion_text, parse_mode="Markdown")
                logger.info(
                    "cmd_atualizar: chat_id=%s promoted to stage %d", chat_id, new_stage
                )
                context.user_data.pop("atualizar_tipo", None)
                return ConversationHandler.END

            paid = max(debt.initial_amount - debt.current_amount, Decimal(0))
            pct = (paid / debt.initial_amount * 100) if debt.initial_amount else Decimal(0)
            pct_str = f"{pct:.1f}".replace(".", ",")

            await update.message.reply_text(
                f"✅ Dívida atualizada!\n\n"
                f"Você pagou: {_fmt_reais(amount)}\n"
                f"Saldo restante: {_fmt_reais(debt.current_amount)}\n"
                f"Pago até agora: {pct_str}%\n\n"
                f"Continue assim! Quando quitar tudo, você avança de estágio. 💪"
            )
            logger.info(
                "cmd_atualizar: chat_id=%s paid %s off debt (%.1f%% paid)",
                chat_id,
                amount,
                float(pct),
            )
        else:
            user = await repo.add_savings(user.id, amount)
            await update.message.reply_text(
                f"✅ Caixinha atualizada!\n\n"
                f"Você guardou: {_fmt_reais(amount)}\n"
                f"Total guardado: {_fmt_reais(user.savings_amount)}\n\n"
                f"Continue guardando! Quando tiver capital suficiente, "
                f"a gente parte para os FIIs. 📈"
            )
            logger.info(
                "cmd_atualizar: chat_id=%s added %s to savings (total=%s)",
                chat_id,
                amount,
                user.savings_amount,
            )

    context.user_data.pop("atualizar_tipo", None)
    return ConversationHandler.END


async def cancel_atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("atualizar_tipo", None)
    await update.message.reply_text("Atualização cancelada.")
    return ConversationHandler.END


def build_atualizar_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("atualizar", cmd_atualizar)],
        states={
            ASK_ATUALIZAR_TIPO: [
                CallbackQueryHandler(
                    ask_atualizar_tipo,
                    pattern=f"^({_CALLBACK_ATUALIZAR_DIVIDA}|{_CALLBACK_ATUALIZAR_SAVINGS})$",
                ),
            ],
            ASK_ATUALIZAR_VALOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_atualizar_valor),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_atualizar)],
        allow_reentry=True,
    )


async def cmd_reserva(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /reserva <valor> — atualiza a reserva de emergência (Estágio 0.5)."""
    chat_id = update.effective_user.id
    args = context.args or []

    amount = _parse_amount(args[0]) if args else None
    if amount is None:
        await update.message.reply_text(
            "Manda o valor guardado dessa vez. Ex: /reserva 200"
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

        if user.stage != 1:
            await update.message.reply_text(
                "O comando /reserva é para quem está guardando a reserva de "
                "emergência (Estágio 0.5). "
                f"Você está no Estágio {_stage_label(user.stage)}."
            )
            return

        fund = await repo.add_emergency_fund_savings(user.id, amount)
        if fund is None:
            await update.message.reply_text(
                "Não encontrei uma reserva de emergência ativa no seu perfil. "
                "Se precisar, manda /start para refazer o onboarding."
            )
            return

        if fund.current_amount >= fund.target_amount:
            await repo.complete_emergency_fund(fund.id)
            await repo.promote_stage(user.id, new_stage=2)
            await update.message.reply_text(
                f"🎉 Reserva completa! Você tem {_fmt_reais(fund.current_amount)} guardados "
                "— 5 meses de segurança pra qualquer imprevisto.\n\n"
                "Agora vamos migrar o foco: cada real guardado a partir de hoje é "
                "um passo rumo ao seu primeiro FII. 📈"
            )
            logger.info("cmd_reserva: chat_id=%s completed emergency fund, promoted to stage 2", chat_id)
        else:
            pct = (fund.current_amount / fund.target_amount * 100) if fund.target_amount else Decimal(0)
            pct_str = f"{pct:.1f}".replace(".", ",")
            await update.message.reply_text(
                f"✅ Reserva atualizada!\n\n"
                f"Guardado: {_fmt_reais(fund.current_amount)} / {_fmt_reais(fund.target_amount)}\n"
                f"Progresso: {pct_str}%\n\n"
                f"Continue guardando! Quando bater a meta, você avança de estágio. 🛡️"
            )
            logger.info(
                "cmd_reserva: chat_id=%s added %s to emergency fund (total=%s)",
                chat_id,
                amount,
                fund.current_amount,
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


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /ajuda — apresenta o Leveling e lista os comandos disponíveis."""
    await update.message.reply_text(
        "*Leveling* — sua jornada de independência financeira 🚀\n\n"
        "O Leveling te acompanha desde o vermelho até os primeiros investimentos, "
        "um passo de cada vez. Sem jargão, sem pressão.\n\n"
        "*Estágios da jornada:*\n"
        "0️⃣ Quitando dívidas — foco em zerar o que deve\n"
        "0️⃣.5️⃣ Reserva de emergência — juntando 5x o gasto essencial\n"
        "1️⃣ Construindo caixinha — acumulando para o primeiro FII\n"
        "2️⃣ Investindo em FIIs — renda passiva crescendo toda semana\n\n"
        "*Comandos disponíveis:*\n"
        "/start — inicia ou refaz o onboarding\n"
        "/atualizar — registra pagamento de dívida (estágio 0) ou dinheiro guardado (estágio 1)\n"
        "/reserva <valor> — atualiza sua reserva de emergência (estágio 0.5)\n"
        "/pausar — pausa os envios semanais\n"
        "/retomar — retoma os envios semanais\n"
        "/reset — apaga seu perfil e começa do zero\n"
        "/ajuda — mostra esta mensagem",
        parse_mode="Markdown",
    )


async def cmd_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para qualquer mensagem fora de um ConversationHandler ativo."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Começar agora", callback_data=CALLBACK_COMECAR_AGORA),
    ]])
    await update.message.reply_text(
        "👋 Olá! Sou o *Leveling* — seu acompanhante de independência financeira.\n\n"
        "A jornada começa onde você está — mesmo que seja no vermelho.\n\n"
        "🎯 *Como funciona:*\n"
        "Você define 3 metas reais — coisas do dia a dia que quer que seus investimentos paguem.\n\n"
        "Exemplo:\n"
        "🥤 Monster → R$ 12/mês\n"
        "🏋️ Academia → R$ 80/mês\n"
        "☕ Café diário → R$ 90/mês\n\n"
        "Cada semana você vê o progresso até essas metas virarem renda passiva de verdade.\n\n"
        "Você pode estar em qualquer ponto:\n"
        "0️⃣ Quitando dívidas\n"
        "0️⃣.5️⃣ Reserva de emergência\n"
        "1️⃣ Guardando na caixinha\n"
        "2️⃣ Investindo em FIIs",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de /reset — apaga o perfil completo e reinicia o onboarding."""
    chat_id = update.effective_user.id

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        deleted = await repo.delete_user(chat_id)

    if deleted:
        await update.message.reply_text(
            "🗑️ Perfil apagado. Vamos começar do zero!\n\n"
            "Manda /start para refazer o onboarding."
        )
        logger.info("cmd_reset: chat_id=%s deleted profile", chat_id)
    else:
        await update.message.reply_text(
            "Não encontrei um perfil para apagar. Manda /start para começar."
        )


async def callback_stage_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback dos botões inline de promoção stage 2→3."""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_user.id
    data = query.data

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_by_chat_id(chat_id)

        if user is None or user.stage != 2:
            await query.edit_message_text("Essa pergunta não é mais válida para o seu perfil.")
            return

        if data == _CALLBACK_SIM:
            await repo.promote_stage(user.id, new_stage=3)
            await query.edit_message_text(
                "🚀 Incrível! Você chegou no *Estágio 2: Investindo em FIIs*!\n\n"
                "A partir de agora você recebe análise semanal da watchlist de FIIs "
                "e sugestões de aporte baseadas no seu perfil.\n\n"
                "Vamos crescer esse patrimônio! 📈",
                parse_mode="Markdown",
            )
            logger.info("callback_stage_check: chat_id=%s promoted to stage 3", chat_id)

        elif data == _CALLBACK_NAO:
            await query.edit_message_text(
                "Tranquilo! Continue guardando — quando tiver R$ 1.000 me avisa. 💰\n\n"
                "Vou perguntar de novo semana que vem."
            )
            logger.info("callback_stage_check: chat_id=%s stays at stage 2", chat_id)


# TODO: hoje não existe um handler de mensagem livre pós-onboarding — quem pulou
# a pergunta de gasto essencial no onboarding só consegue informar o valor depois
# se um handler desse tipo for implementado (fora de escopo por ora). Quando existir,
# ele deve calcular target_amount = valor * 5 e chamar repo.promote_to_emergency_fund
# (ver UserRepository) para usuários sem dívida ativa e ainda sem UserEmergencyFund.
def build_command_handlers() -> list:
    return [
        CommandHandler("pausar", cmd_pausar),
        CommandHandler("retomar", cmd_retomar),
        CommandHandler("reserva", cmd_reserva),
        CommandHandler("ajuda", cmd_ajuda),
        CommandHandler("reset", cmd_reset),
        CallbackQueryHandler(callback_stage_check, pattern=f"^({_CALLBACK_SIM}|{_CALLBACK_NAO})$"),
    ]
