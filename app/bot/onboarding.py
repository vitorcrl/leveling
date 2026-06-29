"""
ConversationHandler de onboarding da jornada financeira.

Fluxo:
  /start
    → ASK_DEBT: tem dívida? (sim/não)
    → [sim] ASK_DEBT_AMOUNT: qual o valor?
    → ASK_BUDGET: qual o aporte mensal?
    → ASK_GOAL: qual a sua meta? (ex: "Monster R$12/mês")
    → ASK_GOAL_VALUE: quanto custa por mês?
    → ASK_PROFILE: perfil de risco (conservador/moderado)
    → ASK_PORTFOLIO: já tem FIIs? (lista de tickers ou /pular)
    → DONE: grava tudo, manda mensagem de boas-vindas

Stage calculado na hora do commit:
  - Tem dívida         → 0
  - Sem dívida, sem FII → 1
  - Sem dívida, com FII → 2
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from app.core.database import AsyncSessionFactory
from app.repositories.user_repository import UserRepository
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

# Estados do ConversationHandler
(
    ASK_DEBT,
    ASK_DEBT_AMOUNT,
    ASK_BUDGET,
    ASK_GOAL,
    ASK_GOAL_VALUE,
    ASK_PROFILE,
    ASK_PORTFOLIO,
) = range(7)

# Chave para guardar dados parciais no context.user_data durante o onboarding
_DATA = "onboarding"


def _d(text: str) -> str:
    """Remove teclado e retorna texto formatado."""
    return text


def _keyboard(*rows: tuple[str, ...]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[btn for btn in row] for row in rows],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def _parse_amount(text: str) -> Decimal | None:
    """Aceita '1500', '1.500', '1.500,50', '1500.50'. Retorna None se inválido."""
    cleaned = text.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        # ex: 1.500,50 → separador de milhar + decimal BR
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        # ex: 1500,50 → decimal BR
        cleaned = cleaned.replace(",", ".")
    elif re.match(r"^\d{1,3}(\.\d{3})+$", cleaned):
        # ex: 1.500 ou 1.500.000 → separador de milhar sem decimal
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
        return value if value > 0 else None
    except InvalidOperation:
        return None


def _parse_tickers(text: str) -> list[str]:
    """Extrai tickers válidos de uma string livre. Ex: 'MXRF11 kncr11, HSML11'."""
    tokens = re.split(r"[\s,;]+", text.upper())
    return [t for t in tokens if re.match(r"^[A-Z]{4}\d{1,2}$", t)]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[_DATA] = {}
    await update.message.reply_text(
        "Olá! Vou te ajudar a montar sua jornada financeira.\n\n"
        "Primeira pergunta: você tem dívidas hoje? (cartão, cheque especial, empréstimo etc.)",
        reply_markup=_keyboard(("Sim", "Não")),
    )
    return ASK_DEBT


async def ask_debt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer in ("sim", "s", "yes"):
        context.user_data[_DATA]["has_debt"] = True
        await update.message.reply_text(
            "Qual o valor total das suas dívidas? (ex: 5000 ou R$ 5.000)",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASK_DEBT_AMOUNT
    else:
        context.user_data[_DATA]["has_debt"] = False
        await update.message.reply_text(
            "Ótimo! Sem dívidas, você já está um passo à frente.\n\n"
            "Quanto você consegue guardar por mês? (ex: 500 ou R$ 1.200)",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASK_BUDGET


async def ask_debt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi o valor. Tenta assim: 5000 ou R$ 5.000"
        )
        return ASK_DEBT_AMOUNT

    context.user_data[_DATA]["debt_amount"] = amount
    await update.message.reply_text(
        "Entendido. Vamos focar em quitar isso!\n\n"
        "Quanto você consegue guardar por mês para pagar a dívida? (ex: 500)"
    )
    return ASK_BUDGET


async def ask_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi. Manda o valor assim: 500 ou R$ 1.200"
        )
        return ASK_BUDGET

    context.user_data[_DATA]["monthly_budget"] = amount
    await update.message.reply_text(
        "Legal! Agora me conta: qual é a sua primeira meta?\n\n"
        "Pensa em algo pequeno que o seu dinheiro vai pagar todo mês. "
        "Por exemplo: 'Netflix', 'Academia', 'Aluguel'.\n\n"
        "Qual é a sua meta?"
    )
    return ASK_GOAL


async def ask_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    goal = update.message.text.strip()
    if len(goal) < 2:
        await update.message.reply_text("Me conta o nome da sua meta!")
        return ASK_GOAL

    context.user_data[_DATA]["goal_name"] = goal
    await update.message.reply_text(
        f"'{goal}' — boa escolha!\n\n"
        f"Quanto custa essa meta por mês? (ex: 50 ou R$ 129,90)"
    )
    return ASK_GOAL_VALUE


async def ask_goal_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi o valor. Tenta: 50 ou R$ 129,90"
        )
        return ASK_GOAL_VALUE

    context.user_data[_DATA]["goal_value_monthly"] = amount
    await update.message.reply_text(
        "Último detalhe sobre investimentos: qual é o seu perfil?",
        reply_markup=_keyboard(
            ("Conservador",),
            ("Moderado",),
        ),
    )
    return ASK_PROFILE


async def ask_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if "conserv" in text:
        profile = "conservador"
    elif "moder" in text:
        profile = "moderado"
    else:
        await update.message.reply_text(
            "Escolhe uma das opções:",
            reply_markup=_keyboard(("Conservador",), ("Moderado",)),
        )
        return ASK_PROFILE

    context.user_data[_DATA]["risk_profile"] = profile
    await update.message.reply_text(
        "Você já tem algum FII na carteira?\n\n"
        "Se sim, manda os tickers separados por espaço ou vírgula. Ex: MXRF11 KNCR11\n"
        "Se não tem, manda /pular",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_PORTFOLIO


async def ask_portfolio_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler para /pular no passo de FIIs."""
    context.user_data[_DATA]["portfolio_tickers"] = []
    return await _finish_onboarding(update, context)


async def ask_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tickers = _parse_tickers(update.message.text)
    if not tickers:
        await update.message.reply_text(
            "Não reconheci nenhum ticker. Manda no formato MXRF11, ou /pular se não tem FIIs."
        )
        return ASK_PORTFOLIO

    context.user_data[_DATA]["portfolio_tickers"] = tickers
    return await _finish_onboarding(update, context)


async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data[_DATA]
    chat_id = update.effective_user.id

    has_debt: bool = data.get("has_debt", False)
    portfolio_tickers: list[str] = data.get("portfolio_tickers", [])

    if has_debt:
        stage = 0
    elif portfolio_tickers:
        stage = 2
    else:
        stage = 1

    try:
        async with AsyncSessionFactory() as session:
            repo = UserRepository(session)
            await repo.save_onboarding(
                chat_id=chat_id,
                stage=stage,
                monthly_budget=data["monthly_budget"],
                risk_profile=data["risk_profile"],
                debt_amount=data.get("debt_amount"),
                goal_name=data["goal_name"],
                goal_value_monthly=data["goal_value_monthly"],
                portfolio_tickers=portfolio_tickers,
            )
    except Exception:
        logger.exception("Failed to save onboarding for chat_id=%s", chat_id)
        await update.message.reply_text(
            "Ops, tive um problema ao salvar seus dados. Tenta de novo com /start."
        )
        return ConversationHandler.END

    stage_messages = {
        0: (
            "Foco total em quitar a dívida! 💪\n"
            "Toda semana te mando um resumo do seu progresso."
        ),
        1: (
            "Hora de construir sua caixinha de investimentos! 🏦\n"
            "Assim que você tiver R$ 1.000 acumulados, a gente parte para os FIIs."
        ),
        2: (
            "Você já tem FIIs — ótimo! 📈\n"
            "Vou te mandar análise semanal da sua carteira."
        ),
    }

    goal_name = data["goal_name"]
    goal_value = data["goal_value_monthly"]

    await update.message.reply_text(
        f"Tudo certo! Sua jornada financeira começa agora.\n\n"
        f"Meta: {goal_name} (R$ {goal_value:.2f}/mês)\n\n"
        f"{stage_messages[stage]}",
        reply_markup=ReplyKeyboardRemove(),
    )

    context.user_data.pop(_DATA, None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_DATA, None)
    await update.message.reply_text(
        "Onboarding cancelado. Manda /start quando quiser começar.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def build_onboarding_handler() -> ConversationHandler:
    """Monta e retorna o ConversationHandler pronto para ser registrado na Application."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_DEBT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_debt),
            ],
            ASK_DEBT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_debt_amount),
            ],
            ASK_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_budget),
            ],
            ASK_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal),
            ],
            ASK_GOAL_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal_value),
            ],
            ASK_PROFILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_profile),
            ],
            ASK_PORTFOLIO: [
                CommandHandler("pular", ask_portfolio_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_portfolio),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
