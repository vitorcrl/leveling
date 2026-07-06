from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models_user import (
    OnboardingEvent,
    User,
    UserDebt,
    UserDividend,
    UserEmergencyFund,
    UserGoal,
    UserPortfolio,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_chat_id(self, chat_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, chat_id: int) -> tuple[User, bool]:
        """Retorna (user, created). created=True se o registro foi criado agora."""
        user = await self.get_by_chat_id(chat_id)
        if user is not None:
            return user, False

        user = User(telegram_chat_id=chat_id)
        self._session.add(user)
        await self._session.flush()  # popula user.id sem commit
        return user, True

    async def save_onboarding(
        self,
        chat_id: int,
        *,
        stage: int,
        monthly_budget: Decimal,
        risk_profile: str,
        debt_amount: Decimal | None,
        savings_amount: Decimal | None,
        goal_name: str,
        goal_value_monthly: Decimal,
        portfolio_shares: dict[str, int],
        monthly_essential_expense: Decimal | None = None,
        onboarding_events: list[dict] | None = None,
    ) -> User:
        """
        Persiste todos os dados do onboarding em uma única transação.
        Chamado pelo ConversationHandler ao receber a última resposta.
        """
        user, _ = await self.get_or_create(chat_id)

        user.stage = stage
        user.monthly_budget = monthly_budget
        user.risk_profile = risk_profile
        user.savings_amount = savings_amount
        user.monthly_essential_expense = monthly_essential_expense
        user.onboarding_complete = True

        if debt_amount is not None:
            debt = UserDebt(
                user_id=user.id,
                initial_amount=debt_amount,
                current_amount=debt_amount,
            )
            self._session.add(debt)

        goal = UserGoal(
            user_id=user.id,
            name=goal_name,
            goal_value_monthly=goal_value_monthly,
        )
        self._session.add(goal)

        for ticker, shares in portfolio_shares.items():
            position = UserPortfolio(
                user_id=user.id,
                ticker=ticker.upper(),
                shares=shares,
            )
            self._session.add(position)

        if stage == 1 and monthly_essential_expense is not None:
            emergency_fund = UserEmergencyFund(
                user_id=user.id,
                target_amount=monthly_essential_expense * 5,
                current_amount=Decimal(0),
            )
            self._session.add(emergency_fund)

        for event in onboarding_events or []:
            self._session.add(
                OnboardingEvent(
                    user_id=user.id,
                    step=event["step"],
                    response_type=event["response_type"],
                    raw_value=event.get("raw_value"),
                )
            )

        await self._session.commit()
        return user

    async def get_all_active(self) -> list[User]:
        """Retorna usuários com onboarding completo que não pausaram os envios."""
        result = await self._session.execute(
            select(User).where(
                User.onboarding_complete.is_(True),
                User.paused.is_(False),
            )
        )
        return list(result.scalars().all())

    async def set_paused(self, user_id, paused: bool) -> User:
        """Liga/desliga o envio proativo do digest — controle explícito via /pausar e /retomar."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.paused = paused
        await self._session.commit()
        return user

    async def set_digest_weekday(self, user_id, weekday: int) -> User:
        """Define o dia da semana (0=segunda ... 6=domingo) em que o usuário recebe o digest."""
        if not 0 <= weekday <= 6:
            raise ValueError(f"weekday deve estar entre 0 e 6, recebido: {weekday}")
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.digest_weekday = weekday
        await self._session.commit()
        return user

    async def update_profile_summary(self, user_id, summary: dict | None) -> User:
        """Persiste o perfil sintetizado por IA (ver app/services/profile_service.py)."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.user_profile_summary = summary
        await self._session.commit()
        return user

    async def get_active_debt(self, user_id) -> UserDebt | None:
        result = await self._session.execute(
            select(UserDebt)
            .where(UserDebt.user_id == user_id, UserDebt.current_amount > 0)
            .order_by(UserDebt.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_debt_amount(self, user_id, new_amount: Decimal) -> UserDebt | None:
        """Atualiza current_amount da dívida ativa. Retorna None se não há dívida ativa."""
        debt = await self.get_active_debt(user_id)
        if debt is None:
            return None
        debt.current_amount = new_amount
        await self._session.commit()
        return debt

    async def add_debt_payment(self, user_id, paid_amount: Decimal) -> UserDebt | None:
        """Abate paid_amount do saldo da dívida ativa. Retorna None se não há dívida ativa."""
        debt = await self.get_active_debt(user_id)
        if debt is None:
            return None
        debt.current_amount = max(debt.current_amount - paid_amount, Decimal(0))
        await self._session.commit()
        return debt

    async def get_active_emergency_fund(self, user_id) -> UserEmergencyFund | None:
        result = await self._session.execute(
            select(UserEmergencyFund)
            .where(
                UserEmergencyFund.user_id == user_id,
                UserEmergencyFund.completed_at.is_(None),
            )
            .order_by(UserEmergencyFund.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_emergency_fund_savings(
        self, user_id, amount: Decimal
    ) -> UserEmergencyFund | None:
        """Soma amount ao current_amount da reserva de emergência ativa. Retorna None se não há reserva ativa."""
        fund = await self.get_active_emergency_fund(user_id)
        if fund is None:
            return None
        fund.current_amount = fund.current_amount + amount
        await self._session.commit()
        return fund

    async def promote_to_emergency_fund(self, user_id, target_amount: Decimal) -> User:
        """Promove o usuário para o Estágio 0.5 (reserva) e cria o UserEmergencyFund."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.stage = 1
        user.stage_check_sent_at = None
        self._session.add(
            UserEmergencyFund(
                user_id=user.id,
                target_amount=target_amount,
                current_amount=Decimal(0),
            )
        )
        await self._session.commit()
        return user

    async def complete_emergency_fund(self, fund_id) -> None:
        """Marca a reserva de emergência como concluída."""
        result = await self._session.execute(
            select(UserEmergencyFund).where(UserEmergencyFund.id == fund_id)
        )
        fund = result.scalar_one()
        fund.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.commit()

    async def add_savings(self, user_id, amount: Decimal) -> User:
        """Soma amount ao savings_amount do usuário (Estágio 1 — caixinha)."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.savings_amount = (user.savings_amount or Decimal(0)) + amount
        await self._session.commit()
        return user

    async def mark_debt_celebrated(self, debt_id, milestone: Decimal) -> None:
        """Registra o último múltiplo de R$100 quitado já celebrado no digest."""
        result = await self._session.execute(select(UserDebt).where(UserDebt.id == debt_id))
        debt = result.scalar_one()
        debt.last_celebrated_amount = milestone
        await self._session.commit()

    async def promote_stage(self, user_id, new_stage: int) -> User:
        """Promove o usuário para o novo stage e limpa stage_check_sent_at."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.stage = new_stage
        user.stage_check_sent_at = None
        await self._session.commit()
        return user

    async def mark_stage_check_sent(self, user_id) -> None:
        """Registra que a pergunta de promoção foi enviada agora."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.stage_check_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.commit()

    async def delete_user(self, chat_id: int) -> bool:
        """Apaga o usuário e todos os dados relacionados. Retorna True se existia."""
        from sqlalchemy import delete as sql_delete

        result = await self._session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return False

        for model in (
            UserDividend,
            UserPortfolio,
            UserDebt,
            UserGoal,
            UserEmergencyFund,
            OnboardingEvent,
        ):
            await self._session.execute(
                sql_delete(model).where(model.user_id == user.id)
            )
        await self._session.delete(user)
        await self._session.commit()
        return True

    async def get_active_goal(self, user_id) -> UserGoal | None:
        result = await self._session.execute(
            select(UserGoal)
            .where(UserGoal.user_id == user_id, UserGoal.achieved_at.is_(None))
            .order_by(UserGoal.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_onboarding_events(self, user_id) -> list[OnboardingEvent]:
        """Lê os eventos de onboarding de um usuário — consumido só por profile_service."""
        result = await self._session.execute(
            select(OnboardingEvent)
            .where(OnboardingEvent.user_id == user_id)
            .order_by(OnboardingEvent.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_portfolio(self, user_id) -> list[UserPortfolio]:
        """Lê a carteira de FIIs autodeclarada do usuário — consumido por ai_context."""
        result = await self._session.execute(
            select(UserPortfolio)
            .where(UserPortfolio.user_id == user_id)
            .order_by(UserPortfolio.ticker.asc())
        )
        return list(result.scalars().all())

    async def get_recent_dividends(self, user_id, since: date) -> list[UserDividend]:
        """Lê dividendos informados pelo usuário desde `since` — consumido por ai_context."""
        result = await self._session.execute(
            select(UserDividend)
            .where(UserDividend.user_id == user_id, UserDividend.received_date >= since)
            .order_by(UserDividend.received_date.desc())
        )
        return list(result.scalars().all())

    async def get_portfolio_position(self, user_id, ticker: str) -> UserPortfolio | None:
        """
        Busca a posição do usuário num ticker específico. Sem chamador hoje —
        preparado para o cálculo automático de dividendo via brapi.dev
        (precisa saber quantas cotas o usuário tem pra multiplicar pelo
        provento por cota).
        """
        result = await self._session.execute(
            select(UserPortfolio).where(
                UserPortfolio.user_id == user_id, UserPortfolio.ticker == ticker.upper()
            )
        )
        return result.scalar_one_or_none()

    async def add_dividend(
        self,
        user_id,
        *,
        ticker: str,
        amount_per_share: Decimal,
        shares_at_time: int,
        received_date: date,
    ) -> UserDividend:
        """
        Registra um dividendo do usuário. Sem chamador hoje — preparado para
        o cálculo automático de dividendo via brapi.dev (ver
        get_portfolio_position); o comando manual /dividendo foi revertido.
        """
        total_received = amount_per_share * shares_at_time
        dividend = UserDividend(
            user_id=user_id,
            ticker=ticker.upper(),
            received_date=received_date,
            amount_per_share=amount_per_share,
            shares_at_time=shares_at_time,
            total_received=total_received,
        )
        self._session.add(dividend)
        await self._session.commit()
        return dividend
