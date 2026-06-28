from app.core.config import Settings


class TestFIIWatchlistTickers:
    def test_parses_comma_separated_tickers(self):
        s = Settings(FII_WATCHLIST="KNCR11,MXRF11,HSML11")
        assert s.fii_watchlist_tickers == ["KNCR11", "MXRF11", "HSML11"]

    def test_strips_whitespace_around_tickers(self):
        s = Settings(FII_WATCHLIST=" KNCR11 , MXRF11 ")
        assert s.fii_watchlist_tickers == ["KNCR11", "MXRF11"]

    def test_uppercases_tickers(self):
        s = Settings(FII_WATCHLIST="kncr11,mxrf11")
        assert s.fii_watchlist_tickers == ["KNCR11", "MXRF11"]

    def test_ignores_empty_entries(self):
        # Cobre a condição `if t.strip()` — entradas vazias são descartadas
        s = Settings(FII_WATCHLIST="KNCR11,,MXRF11,")
        assert s.fii_watchlist_tickers == ["KNCR11", "MXRF11"]

    def test_returns_empty_list_for_empty_watchlist(self):
        s = Settings(FII_WATCHLIST="")
        assert s.fii_watchlist_tickers == []
