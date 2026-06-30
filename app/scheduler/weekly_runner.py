"""
Scheduler semanal da jornada financeira.

Itera por todos os usuários com onboarding completo e envia uma mensagem
personalizada baseada no stage atual de cada um.

Invocado via: python -m app.scheduler.weekly_runner
Geralmente chamado por cron toda segunda-feira às 8h.

Stage 0 — quitando dívida: progresso no pagamento + motivação
Stage 1 — acumulando caixinha: saldo acumulado + proximidade da meta de R$1k
Stage 2 — investindo em FIIs: resumo da carteira + sugestão de aporte
"""

import asyncio
import logging
from decimal import Decimal

from telegram import Bot

from app.adapters.delivery.telegram_adapter import TelegramAdapter
from app.core.config import get_settings
from app.domain.models_user import User, UserDebt, UserGoal
from app.domain.ports import DeliveryPort
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_stage0_message(user: User, debt: UserDebt | None, goal: UserGoal | None) -> str:
    lines = ["*Semana de progresso — Estágio 0: Quitando a dívida* 💪"]
    if debt is not None:
        paid = max(debt.initial_amount - debt.current_amount, Decimal(0))
        pct = (paid / debt.initial_amount * 100) if debt.initial_amount else Decimal(0)
        lines.append(f"\nDívida inicial: {_fmt(debt.initial_amount)}")
        lines.append(f"Saldo atual: {_fmt(debt.current_amount)}")
        pct_str = f"{pct:.1f}".replace(".", ",")
        lines.append(f"Pago até agora: {_fmt(paid)} ({pct_str}%)")
    else:
        lines.append("\nAtualize seu saldo de dívida para acompanhar o progresso.")
    lines.append(f"\nAporte mensal planejado: {_fmt(user.monthly_budget)}")
    if goal:
        lines.append(f"\nSua meta: *{goal.name}* ({_fmt(goal.goal_value_monthly)}/mês)")
        lines.append("Quita a dívida e em breve esse dinheiro trabalha por você! 🎯")
    return "\n".join(lines)


def _build_stage1_message(user: User, goal: UserGoal | None) -> str:
    budget = user.monthly_budget or Decimal(0)
    target = Decimal("1000")
    lines = ["*Semana de progresso — Estágio 1: Construindo a caixinha* 🏦"]
    lines.append(f"\nAporte mensal: {_fmt(budget)}")
    if budget > 0:
        months_to_target = target / budget
        lines.append(f"Faltam ~{months_to_target:.0f} meses para atingir R$ 1.000")
    lines.append("\nContinue guardando. Quando tiver R$ 1.000, a gente parte para os FIIs!")
    if goal:
        lines.append(f"\nSua meta: *{goal.name}* ({_fmt(goal.goal_value_monthly)}/mês)")
        lines.append("Cada real guardado te aproxima dessa meta. 💰")
    return "\n".join(lines)


def _build_stage2_message(user: User, goal: UserGoal | None) -> str:
    lines = ["*Semana de progresso — Estágio 2: Investindo em FIIs* 📈"]
    lines.append(f"\nPerfil: {user.risk_profile or 'não informado'}")
    lines.append(f"Aporte mensal: {_fmt(user.monthly_budget)}")
    if goal:
        lines.append(f"\nSua meta: *{goal.name}* ({_fmt(goal.goal_value_monthly)}/mês)")
    lines.append(
        "\nSeu pipeline de FIIs roda toda semana. "
        "Se houver alertas na sua carteira, você recebe um aviso separado."
    )
    lines.append("\nContinue reinvestindo os proventos para acelerar o efeito composto! 🚀")
    return "\n".join(lines)


async def send_weekly_digest(delivery: DeliveryPort) -> dict[str, int]:
    from app.core.database import AsyncSessionFactory

    sent = skipped = errors = 0

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        users = await repo.get_all_active()

        logger.info("weekly_runner: %d active users found", len(users))

        for user in users:
            try:
                debt = await repo.get_active_debt(user.id)
                goal = await repo.get_active_goal(user.id)

                if user.stage == 0:
                    message = _build_stage0_message(user, debt, goal)
                elif user.stage == 1:
                    message = _build_stage1_message(user, goal)
                elif user.stage == 2:
                    message = _build_stage2_message(user, goal)
                else:
                    logger.warning(
                        "weekly_runner: unknown stage=%d for chat_id=%s — skipping",
                        user.stage,
                        user.telegram_chat_id,
                    )
                    skipped += 1
                    continue

                await delivery.send(message, chat_id=user.telegram_chat_id)
                sent += 1
                logger.info(
                    "weekly_runner: sent stage-%d digest to chat_id=%s",
                    user.stage,
                    user.telegram_chat_id,
                )
            except Exception:
                errors += 1
                logger.exception(
                    "weekly_runner: failed for chat_id=%s", user.telegram_chat_id
                )

    return {"sent": sent, "skipped": skipped, "errors": errors}


async def run() -> None:
    settings = get_settings()
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    delivery = TelegramAdapter(bot)
    result = await send_weekly_digest(delivery)
    logger.info("weekly_runner: done — %s", result)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run())
