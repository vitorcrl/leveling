from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=1)
def _engine():
    from app.core.config import get_settings
    return create_async_engine(get_settings().DATABASE_URL, echo=False)


@lru_cache(maxsize=1)
def _factory() -> async_sessionmaker:
    return async_sessionmaker(
        bind=_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


class _LazySessionFactory:
    """
    Proxy que adia a criação do engine para a primeira chamada.
    Mantém a interface `async with AsyncSessionFactory() as session:`
    sem criar conexão em import time.
    """

    def __call__(self):
        return _factory()()

    def __getattr__(self, name):
        return getattr(_factory(), name)


AsyncSessionFactory = _LazySessionFactory()
