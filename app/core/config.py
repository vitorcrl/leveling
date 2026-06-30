from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Banco de dados ---
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/bot_db"

    # --- Claude API ---
    ANTHROPIC_API_KEY: str = ""
    AI_RELEVANCE_MODEL: str = "claude-haiku-4-5-20251001"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = ""

    # --- brapi.dev ---
    BRAPI_TOKEN: str = ""
    BRAPI_BASE_URL: str = "https://brapi.dev/api"

    # --- Watchlist e orçamento ---
    ASSET_WATCHLIST: str = "KNCR11,MXRF11,HSML11,BRCO11,LVBI11"
    WEEKLY_BUDGET: float = 500.00
    REINVEST_INCOME: bool = True
    JOURNEY_CRON_HOUR: int = 10

    # --- Thresholds das regras de ativos ---
    ASSET_MIN_DY: float = 8.0
    ASSET_MAX_PVP: float = 1.15
    ASSET_PVP_DISCOUNT: float = 0.80
    ASSET_MAX_VACANCIA: float = 15.0
    ASSET_MAX_LTV: float = 70.0
    ASSET_MIN_LIQUIDEZ: float = 500_000
    ASSET_MAX_PRICE_DROP: float = 5.0
    ASSET_MIN_DELTA_DY: float = -1.0

    @property
    def watchlist_tickers(self) -> list[str]:
        return [t.strip().upper() for t in self.ASSET_WATCHLIST.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()