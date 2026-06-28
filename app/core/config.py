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
    TELEGRAM_CHAT_ID: str = ""

    # --- brapi.dev ---
    BRAPI_TOKEN: str = ""
    BRAPI_BASE_URL: str = "https://brapi.dev/api"

    # --- Watchlist e orçamento FIIs ---
    FII_WATCHLIST: str = "KNCR11,MXRF11,HSML11,BRCO11,LVBI11"
    FII_WEEKLY_BUDGET: float = 500.00
    FII_REINVEST_PROVENTOS: bool = True
    FII_CRON_HOUR: int = 10

    # --- Thresholds das regras de FIIs ---
    FII_MIN_DY: float = 8.0
    FII_MAX_PVP: float = 1.15
    FII_PVP_DISCOUNT: float = 0.80
    FII_MAX_VACANCIA: float = 15.0
    FII_MAX_LTV: float = 70.0
    FII_MIN_LIQUIDEZ: float = 500_000
    FII_MAX_PRICE_DROP: float = 5.0
    FII_MIN_DELTA_DY: float = -1.0

    @property
    def fii_watchlist_tickers(self) -> list[str]:
        return [t.strip().upper() for t in self.FII_WATCHLIST.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()