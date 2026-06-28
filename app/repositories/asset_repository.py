from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models_asset import AssetSnapshot
from app.domain.models_asset_orm import AssetSnapshotORM


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_snapshot(self, snapshot: AssetSnapshot) -> None:
        """Persiste o snapshot do dia. Ignora silenciosamente se (ticker, date) já existe."""
        existing = await self.session.execute(
            select(AssetSnapshotORM).where(
                AssetSnapshotORM.ticker == snapshot.ticker,
                AssetSnapshotORM.date == snapshot.date,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return

        orm = AssetSnapshotORM(
            ticker=snapshot.ticker,
            market=snapshot.market,
            date=snapshot.date,
            price=snapshot.price,
            dy_12m=snapshot.dy_12m,
            pvp=snapshot.pvp,
            liquidez=snapshot.liquidez,
            vacancia=snapshot.vacancia,
            ltv=snapshot.ltv,
            provento_anunciado=snapshot.provento_anunciado,
        )
        self.session.add(orm)
        await self.session.commit()

    async def get_previous_snapshot(
        self, ticker: str, before: date, days_back: int = 8
    ) -> AssetSnapshotORM | None:
        """Retorna o snapshot mais recente de um ticker anterior à data informada."""
        cutoff = before - timedelta(days=days_back)
        result = await self.session.execute(
            select(AssetSnapshotORM)
            .where(
                AssetSnapshotORM.ticker == ticker,
                AssetSnapshotORM.date >= cutoff,
                AssetSnapshotORM.date < before,
            )
            .order_by(AssetSnapshotORM.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_snapshots_since(self, ticker: str, since: date) -> int:
        """
        Conta quantos snapshots existem para o ticker desde a data informada.
        Usado como proxy de streak pelo narrator: quanto mais snapshots, mais
        semanas consecutivas o pipeline rodou para esse fundo.
        Nota: não filtra por regra — AssetSnapshotORM não armazena qual regra
        disparou. O narrator usa esse número como aproximação de "há N semanas".
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(AssetSnapshotORM)
            .where(
                AssetSnapshotORM.ticker == ticker,
                AssetSnapshotORM.date >= since,
            )
        )
        return result.scalar_one() or 0

    async def sum_proventos(self, ticker: str, since: date) -> float:
        """Soma dos proventos anunciados de um ticker desde a data informada."""
        result = await self.session.execute(
            select(func.sum(AssetSnapshotORM.provento_anunciado)).where(
                AssetSnapshotORM.ticker == ticker,
                AssetSnapshotORM.date >= since,
                AssetSnapshotORM.provento_anunciado.isnot(None),
            )
        )
        return float(result.scalar_one() or 0.0)
