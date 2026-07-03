from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models_user import User, UserDebt, UserDividend, UserGoal, UserPortfolio


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
        portfolio_tickers: list[str],
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

        for ticker in portfolio_tickers:
            position = UserPortfolio(
                user_id=user.id,
                ticker=ticker.upper(),
                shares=0,
            )
            self._session.add(position)

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
        from datetime import datetime, timezone
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

        for model in (UserDividend, UserPortfolio, UserDebt, UserGoal):
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
