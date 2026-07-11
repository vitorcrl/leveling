"""
ConversationHandler de onboarding da jornada financeira.

Fluxo:
  /start
    → ASK_DEBT: tem dívida? (sim/não)
    → [sim] ASK_DEBT_AMOUNT: qual o valor?
    → ASK_ESSENTIAL_EXPENSE: quanto gasta por mês com o essencial? (roda para todos,
      inclusive quem tem dívida — o dado só vira reserva de emergência quando o
      usuário não tem dívida ativa; "não sei" ou /pular seguem sem gravar valor)
    → ASK_BUDGET: qual o aporte mensal?
    → [sem dívida] ASK_SAVINGS: já tem algum dinheiro guardado?
    → ASK_GOAL: qual a sua meta?
    → ASK_GOAL_VALUE: quanto custa por mês?
    → ASK_PROFILE: perfil de risco (inline: conservador/moderado com explicação)
    → ASK_HAS_PORTFOLIO: já tem FIIs? (sim/não via botões)
    → [sim] ASK_PORTFOLIO: lista de tickers
      → ASK_PORTFOLIO_SHARES: quantas cotas de cada ticker, uma pergunta por vez
    → [não] ASK_KNOWS_FII: já conhece FIIs? (sim/não via botões — explica se não souber)
    → DONE: grava tudo, manda mensagem de boas-vindas + comandos disponíveis

Stage calculado na hora do commit:
  - Tem dívida                                      → 0
  - Sem dívida, informou gasto essencial            → 1 (reserva de emergência)
  - Sem dívida, sem FII, sem gasto essencial         → 2 (caixinha rumo ao 1º FII)
  - Sem dívida, com FII                              → 3 (investindo em FIIs)
"""

import asyncio
import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.core.database import AsyncSessionFactory
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# Estados do ConversationHandler
(
    ASK_DEBT,
    ASK_DEBT_AMOUNT,
    ASK_ESSENTIAL_EXPENSE,
    ASK_BUDGET,
    ASK_SAVINGS,
    ASK_GOAL,
    ASK_GOAL_VALUE,
    ASK_PROFILE,
    ASK_HAS_PORTFOLIO,
    ASK_PORTFOLIO,
    ASK_PORTFOLIO_SHARES,
    ASK_KNOWS_FII,
) = range(12)

# tokens aceitos como "não sei" na pergunta de gasto essencial (case-insensitive)
_DONT_KNOW_TOKENS = {"não sei", "nao sei", "não faço ideia", "nao faco ideia"}

_CALCULADORA_URL = "https://investidorsardinha.r7.com/calculadoras/custos-fixos/"

_DATA = "onboarding"

_CALLBACK_DEBT_SIM = "onb_debt_sim"
_CALLBACK_DEBT_NAO = "onb_debt_nao"
_CALLBACK_CONSERVADOR = "profile_conservador"
_CALLBACK_MODERADO = "profile_moderado"
_CALLBACK_HAS_PORTFOLIO_SIM = "onb_portfolio_sim"
_CALLBACK_HAS_PORTFOLIO_NAO = "onb_portfolio_nao"
_CALLBACK_KNOWS_FII_SIM = "onb_knows_fii_sim"
_CALLBACK_KNOWS_FII_NAO = "onb_knows_fii_nao"
_CALLBACK_PORTFOLIO_SKIP = "onb_portfolio_skip"

# callback_data do botão inline "🚀 Começar agora" enviado por cmd_unknown_message —
# entra no onboarding igual ao /start.
CALLBACK_COMECAR_AGORA = "unknown_start"


def _parse_amount(text: str) -> Decimal | None:
    """Aceita '1500', '1.500', '1.500,50', '1500.50'. Retorna None se inválido ou zero."""
    cleaned = text.strip().replace("R$", "").replace(" ", "")
    # pega só o primeiro token numérico caso venha "Sim 1000"
    cleaned = re.split(r"\s+", cleaned)[0]
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif re.match(r"^\d{1,3}(\.\d{3})+$", cleaned):
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


def _parse_shares(text: str) -> int | None:
    """Aceita só dígitos positivos (quantidade de cotas). Ex: '10'. None se inválido ou zero."""
    cleaned = text.strip()
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


_MAX_RAW_VALUE_LEN = 200


def _record_event(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    step: str,
    response_type: str,
    raw_value: str | None = None,
) -> None:
    """
    Acumula um evento de analytics em memória (ver OnboardingEvent) — inserido
    no banco só quando `save_onboarding` roda, na mesma transação. Não afeta
    nenhuma lógica de negócio, é só instrumentação.
    """
    events: list = context.user_data[_DATA].setdefault("events", [])
    events.append({
        "step": step,
        "response_type": response_type,
        "raw_value": raw_value[:_MAX_RAW_VALUE_LEN] if raw_value else raw_value,
    })


# Referências às tasks em voo — sem isso, o garbage collector pode coletar a
# task no meio da execução (asyncio.create_task não mantém referência forte).
_background_tasks: set[asyncio.Task] = set()


def _trigger_profile_generation(user_id) -> None:
    """
    Dispara a geração do perfil de IA em background, sem bloquear o onboarding.
    Se falhar, o perfil fica NULL e o narrator cai no fallback estático — ver
    app/services/profile_service.py.
    """
    from app.services.profile_service import generate_and_store_profile

    task = asyncio.create_task(generate_and_store_profile(user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[_DATA] = {}

    # Entry point duplo: /start manda update.message; o botão inline
    # "Começar agora" (callback_unknown_start) manda update.callback_query.
    if update.message is not None:
        reply = update.message.reply_text
    else:
        await update.callback_query.answer()
        reply = update.callback_query.message.reply_text

    await reply(
        "*Bem-vindo ao Leveling!* 🚀\n\n"
        "Aqui você acompanha sua jornada financeira desde o vermelho até os primeiros investimentos.\n\n"
        "São só algumas perguntas rápidas para montar o seu perfil. Vamos lá?",
        parse_mode="Markdown",
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim, tenho", callback_data=_CALLBACK_DEBT_SIM),
        InlineKeyboardButton("🙅 Não tenho", callback_data=_CALLBACK_DEBT_NAO),
    ]])
    await reply(
        "Você tem dívidas hoje?\n"
        "(cartão, cheque especial, empréstimo etc.)",
        reply_markup=keyboard,
    )
    return ASK_DEBT


async def ask_debt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == _CALLBACK_DEBT_SIM:
        context.user_data[_DATA]["has_debt"] = True
        _record_event(context, step="debt", response_type="answered", raw_value="sim")
        await query.edit_message_text(
            "Qual o valor total das suas dívidas?\n\n"
            "Manda só o número, sem R$ ou pontos. Ex: 5000",
        )
        return ASK_DEBT_AMOUNT
    else:
        context.user_data[_DATA]["has_debt"] = False
        _record_event(context, step="debt", response_type="answered", raw_value="não")
        await query.edit_message_text(
            "Ótimo! Sem dívidas, você já está um passo à frente. 👏"
        )
        # Estágio 0.5 (reserva de emergência) temporariamente fora do onboarding —
        # MVP simplificado para 3 passos (dívida → caixinha → FIIs). O fluxo de
        # ASK_ESSENTIAL_EXPENSE continua implementado e funcional (ver
        # _send_ask_essential_expense, ask_essential_expense, /reserva em
        # commands.py) para quando reativarmos. Só não é mais perguntado aqui.
        return await _after_essential_expense(update, context)


async def ask_debt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi. Manda só o número, sem pontos ou vírgulas. Ex: 5000"
        )
        return ASK_DEBT_AMOUNT

    context.user_data[_DATA]["debt_amount"] = amount
    _record_event(
        context, step="debt_amount", response_type="answered", raw_value=update.message.text
    )
    await update.message.reply_text("Entendido. Vamos focar em quitar isso! 💪")
    # Estágio 0.5 (reserva de emergência) temporariamente fora do onboarding —
    # ver comentário equivalente em ask_debt.
    return await _after_essential_expense(update, context)


# Não chamada no fluxo ativo hoje (Estágio 0.5 temporariamente desligado do
# onboarding — ver comentário em ask_debt). Mantida para reativação futura.
async def _send_ask_essential_expense(reply) -> None:
    await reply(
        "Quanto você gasta por mês com o essencial — aluguel, contas, mercado?\n"
        "Fica só entre a gente, ninguém mais vê isso 🔒\n\n"
        "Se não souber, manda 'não sei' que eu te ajudo. Ou /pular se preferir "
        "seguir sem essa parte por enquanto."
    )


async def ask_essential_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()

    if text in _DONT_KNOW_TOKENS:
        _record_event(
            context, step="essential_expense", response_type="dont_know", raw_value=update.message.text
        )
        await update.message.reply_text(
            "Sem problema! Essa calculadora te ajuda a somar isso rapidinho:\n"
            f"{_CALCULADORA_URL}\n\n"
            "Quando tiver o número, é só me mandar (mensagem livre, a qualquer "
            "momento). Bora continuar!"
        )
        return await _after_essential_expense(update, context)

    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi. Manda só o número (ex: 1500), 'não sei' ou /pular."
        )
        return ASK_ESSENTIAL_EXPENSE

    context.user_data[_DATA]["monthly_essential_expense"] = amount
    _record_event(
        context, step="essential_expense", response_type="answered", raw_value=update.message.text
    )
    return await _after_essential_expense(update, context)


async def ask_essential_expense_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _record_event(context, step="essential_expense", response_type="skipped")
    return await _after_essential_expense(update, context)


async def _after_essential_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # update pode vir de message (fluxo normal) ou callback_query (chamado
    # direto por ask_debt, quando o usuário não tem dívida — ver comentário lá).
    reply = update.message.reply_text if update.message else update.callback_query.message.reply_text

    if context.user_data[_DATA].get("has_debt"):
        await reply(
            "Quanto você consegue separar por mês para pagar a dívida?\n"
            "Manda só o número. Ex: 500"
        )
    else:
        await reply(
            "Quanto você consegue guardar por mês?\n"
            "Manda só o número. Ex: 500"
        )
    return ASK_BUDGET


async def ask_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text(
            "Não entendi. Manda só o número. Ex: 500"
        )
        return ASK_BUDGET

    context.user_data[_DATA]["monthly_budget"] = amount
    _record_event(context, step="budget", response_type="answered", raw_value=update.message.text)

    # Quem tem dívida não passa pela pergunta de caixinha
    if context.user_data[_DATA].get("has_debt"):
        await update.message.reply_text(
            "Legal! Agora me conta: qual é a sua primeira meta?\n\n"
            "Pensa em algo concreto que o seu dinheiro vai pagar todo mês. "
            "Por exemplo: Netflix, Academia, Monster, Aluguel.\n\n"
            "Qual é a sua meta?"
        )
        return ASK_GOAL

    await update.message.reply_text(
        "Você já tem algum dinheiro guardado? 🏦\n\n"
        "Pode ser na poupança, no Mercado Pago, no Nubank, em qualquer lugar.\n"
        "Se sim, quanto? Se não tem nada ainda, manda 0."
    )
    return ASK_SAVINGS


async def ask_savings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    # aceita "0", "não", "nada", "nenhum" como zero
    if text.lower() in ("0", "não", "nao", "nada", "nenhum", "nenhu"):
        savings = Decimal(0)
    else:
        savings = _parse_amount(text) or Decimal(0)

    context.user_data[_DATA]["savings_amount"] = savings
    _record_event(context, step="savings", response_type="answered", raw_value=text)

    await update.message.reply_text(
        "Agora me conta: qual é a sua primeira meta?\n\n"
        "Pensa em algo concreto que o seu dinheiro vai pagar todo mês. "
        "Por exemplo: Netflix, Academia, Monster, Aluguel.\n\n"
        "Qual é a sua meta?"
    )
    return ASK_GOAL


async def ask_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    goal = update.message.text.strip()
    if len(goal) < 2:
        await update.message.reply_text("Me conta o nome da sua meta!")
        return ASK_GOAL

    context.user_data[_DATA]["goal_name"] = goal
    _record_event(context, step="goal", response_type="answered", raw_value=goal)
    await update.message.reply_text(
        f"'{goal}' — boa escolha! 🎯\n\n"
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
    _record_event(
        context, step="goal_value", response_type="answered", raw_value=update.message.text
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡️ Conservador", callback_data=_CALLBACK_CONSERVADOR),
            InlineKeyboardButton("⚖️ Moderado", callback_data=_CALLBACK_MODERADO),
        ]
    ])
    await update.message.reply_text(
        "Antes de escolher, entenda cada perfil:\n\n"
        "🛡️ *Conservador* — segurança e previsibilidade.\n"
        "FIIs de papel (CRI/CRA): renda consistente, menos volatilidade. "
        "Ideal para quem está começando.\n\n"
        "⚖️ *Moderado* — equilíbrio entre risco e retorno.\n"
        "Mix de papel + logística/shopping: potencial de crescimento de cota "
        "junto com renda mensal.\n\n"
        "Qual é o seu perfil?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return ASK_PROFILE


async def ask_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == _CALLBACK_CONSERVADOR:
        profile = "conservador"
        label = "🛡️ Conservador"
    else:
        profile = "moderado"
        label = "⚖️ Moderado"

    context.user_data[_DATA]["risk_profile"] = profile
    _record_event(context, step="profile", response_type="answered", raw_value=profile)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim, tenho", callback_data=_CALLBACK_HAS_PORTFOLIO_SIM),
        InlineKeyboardButton("🙅 Não tenho", callback_data=_CALLBACK_HAS_PORTFOLIO_NAO),
    ]])
    await query.edit_message_text(
        f"Perfil definido: *{label}*\n\n"
        "Você já tem algum FII na carteira?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return ASK_HAS_PORTFOLIO


async def ask_has_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _record_event(context, step="has_portfolio", response_type="answered", raw_value=query.data)

    if query.data == _CALLBACK_HAS_PORTFOLIO_SIM:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🙅 Não tenho", callback_data=_CALLBACK_PORTFOLIO_SKIP),
        ]])
        await query.edit_message_text(
            "Manda os tickers separados por espaço ou vírgula. Ex: MXRF11 KNCR11",
            reply_markup=keyboard,
        )
        return ASK_PORTFOLIO

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Já conheço", callback_data=_CALLBACK_KNOWS_FII_SIM),
        InlineKeyboardButton("❓ Não sei o que é", callback_data=_CALLBACK_KNOWS_FII_NAO),
    ]])
    await query.edit_message_text(
        "Tudo bem! Você já sabe o que é um FII?",
        reply_markup=keyboard,
    )
    return ASK_KNOWS_FII


async def ask_knows_fii(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data[_DATA]["portfolio_shares"] = {}
    _record_event(context, step="knows_fii", response_type="answered", raw_value=query.data)

    if query.data == _CALLBACK_KNOWS_FII_NAO:
        await query.edit_message_text(
            "🏠 *FII* (Fundo de Investimento Imobiliário) é um jeito de investir "
            "em imóveis sem precisar comprar um imóvel inteiro.\n\n"
            "Você compra cotas e recebe uma parte dos aluguéis e rendimentos "
            "todo mês — direto na sua conta.\n\n"
            "Bora continuar sua jornada! 🚀",
            parse_mode="Markdown",
        )

    return await _finish_onboarding(update, context, error_state=ASK_KNOWS_FII)


async def ask_portfolio_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[_DATA]["portfolio_shares"] = {}
    _record_event(context, step="portfolio", response_type="skipped")
    return await _finish_onboarding(update, context, error_state=ASK_PORTFOLIO)


async def ask_portfolio_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data[_DATA]["portfolio_shares"] = {}
    _record_event(context, step="portfolio", response_type="skipped")
    return await _finish_onboarding(update, context, error_state=ASK_PORTFOLIO)


async def ask_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tickers = _parse_tickers(update.message.text)
    if not tickers:
        await update.message.reply_text(
            "Não reconheci nenhum ticker. Manda no formato MXRF11, ou /pular se não tem FIIs."
        )
        return ASK_PORTFOLIO

    context.user_data[_DATA]["portfolio_tickers_pending"] = tickers
    context.user_data[_DATA]["portfolio_shares"] = {}
    _record_event(
        context, step="portfolio", response_type="answered", raw_value=update.message.text
    )
    await update.message.reply_text(f"Quantas cotas de {tickers[0]} você tem?")
    return ASK_PORTFOLIO_SHARES


async def ask_portfolio_shares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data[_DATA]
    pending: list[str] = data["portfolio_tickers_pending"]
    current_ticker = pending[0]

    shares = _parse_shares(update.message.text)
    if shares is None:
        await update.message.reply_text(
            f"Não entendi. Manda só o número de cotas de {current_ticker}. Ex: 10"
        )
        return ASK_PORTFOLIO_SHARES

    data["portfolio_shares"][current_ticker] = shares
    pending.pop(0)

    if pending:
        await update.message.reply_text(f"Quantas cotas de {pending[0]} você tem?")
        return ASK_PORTFOLIO_SHARES

    data["portfolio_tickers_pending"] = []
    return await _finish_onboarding(update, context, error_state=ASK_PORTFOLIO_SHARES)


async def _finish_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE, error_state: int
) -> int:
    """
    error_state: estado da conversa para onde voltar se `save_onboarding` falhar
    (erro de banco, conexão etc). Nunca encerramos a conversa nesse caso — o
    usuário mantém `context.user_data[_DATA]` intacto e pode tentar de novo.
    """
    data = context.user_data[_DATA]
    # update pode vir de message (portfolio) ou callback_query (pular via comando)
    chat_id = update.effective_user.id

    has_debt: bool = data.get("has_debt", False)
    portfolio_shares: dict[str, int] = data.get("portfolio_shares", {})
    monthly_essential_expense = data.get("monthly_essential_expense")

    if has_debt:
        stage = 0
    elif portfolio_shares:
        stage = 3
    elif monthly_essential_expense is not None:
        stage = 1  # Estágio 0.5 — reserva de emergência
    else:
        stage = 2  # caixinha rumo ao 1º FII (pulou a pergunta de gasto essencial)

    try:
        async with AsyncSessionFactory() as session:
            repo = UserRepository(session)
            user = await repo.save_onboarding(
                chat_id=chat_id,
                stage=stage,
                monthly_budget=data["monthly_budget"],
                risk_profile=data["risk_profile"],
                debt_amount=data.get("debt_amount"),
                savings_amount=data.get("savings_amount"),
                goal_name=data["goal_name"],
                goal_value_monthly=data["goal_value_monthly"],
                portfolio_shares=portfolio_shares,
                monthly_essential_expense=monthly_essential_expense,
                onboarding_events=data.get("events", []),
            )
    except Exception:
        logger.exception("Failed to save onboarding for chat_id=%s", chat_id)
        msg = "Ops, tive um problema ao salvar seus dados. Tenta de novo mandando sua última resposta."
        if update.message:
            await update.message.reply_text(msg)
        else:
            await update.callback_query.message.reply_text(msg)
        return error_state

    _trigger_profile_generation(user.id)

    goal_name = data["goal_name"]
    goal_value = data["goal_value_monthly"]

    stage_messages = {
        0: (
            "🎯 *Próximo passo:* toda semana te mando um resumo do progresso.\n"
            "Quando quitar tudo, manda /atualizar e você avança para a próxima etapa!"
        ),
        1: (
            "🛡️ *Próximo passo:* guarda na caixinha do Nubank ou Mercado Pago (100% CDI) — "
            "esse é o seu colchão de segurança.\n"
            "Manda /reserva <valor> sempre que guardar mais. Quando bater 5x seu gasto "
            "essencial, a gente parte para o 1º FII!"
        ),
        2: (
            "🏦 *Próximo passo:* guarda na caixinha do Nubank ou Mercado Pago (100% CDI).\n"
            "Quando tiver R$ 1.000 guardados, me avisa e a gente parte para os FIIs!"
        ),
        3: (
            "📈 *Próximo passo:* toda semana você recebe análise da sua carteira "
            "e o progresso dos seus dividendos rumo à meta."
        ),
    }

    commands_text = (
        "\n\n*Comandos disponíveis:*\n"
        "/atualizar — atualiza seu saldo de dívida (stage 0)\n"
        "/ajuda — mostra todos os comandos"
    )

    reply_text = (
        f"✅ Tudo certo! Sua jornada financeira começa agora.\n\n"
        f"Meta: *{goal_name}* (R$ {goal_value:.2f}/mês)\n\n"
        f"{stage_messages[stage]}"
        f"{commands_text}"
    )

    if update.message:
        await update.message.reply_text(
            reply_text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.callback_query.message.reply_text(
            reply_text,
            parse_mode="Markdown",
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
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(start, pattern=f"^{CALLBACK_COMECAR_AGORA}$"),
        ],
        states={
            ASK_DEBT: [
                CallbackQueryHandler(
                    ask_debt,
                    pattern=f"^({_CALLBACK_DEBT_SIM}|{_CALLBACK_DEBT_NAO})$",
                ),
            ],
            ASK_DEBT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_debt_amount),
            ],
            ASK_ESSENTIAL_EXPENSE: [
                CommandHandler("pular", ask_essential_expense_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_essential_expense),
            ],
            ASK_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_budget),
            ],
            ASK_SAVINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_savings),
            ],
            ASK_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal),
            ],
            ASK_GOAL_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal_value),
            ],
            ASK_PROFILE: [
                CallbackQueryHandler(
                    ask_profile_callback,
                    pattern=f"^({_CALLBACK_CONSERVADOR}|{_CALLBACK_MODERADO})$",
                ),
            ],
            ASK_HAS_PORTFOLIO: [
                CallbackQueryHandler(
                    ask_has_portfolio,
                    pattern=f"^({_CALLBACK_HAS_PORTFOLIO_SIM}|{_CALLBACK_HAS_PORTFOLIO_NAO})$",
                ),
            ],
            ASK_PORTFOLIO: [
                CommandHandler("pular", ask_portfolio_skip),
                CallbackQueryHandler(
                    ask_portfolio_skip_callback,
                    pattern=f"^{_CALLBACK_PORTFOLIO_SKIP}$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_portfolio),
            ],
            ASK_PORTFOLIO_SHARES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_portfolio_shares),
            ],
            ASK_KNOWS_FII: [
                CallbackQueryHandler(
                    ask_knows_fii,
                    pattern=f"^({_CALLBACK_KNOWS_FII_SIM}|{_CALLBACK_KNOWS_FII_NAO})$",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
