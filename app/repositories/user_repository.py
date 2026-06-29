from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models_user import User, UserDebt, UserGoal, UserPortfolio


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
