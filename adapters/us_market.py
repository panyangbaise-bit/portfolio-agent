from datetime import datetime
from typing import Optional
import yfinance as yf

from adapters.base import MarketAdapter


class USMarketAdapter(MarketAdapter):
    """US stock data via yfinance."""

    MARKET = "US"

    def get_price(self, ticker: str) -> dict:
        stock = yf.Ticker(ticker)
        info = stock.info
        fast = stock.fast_info
        return {
            "ticker": ticker.upper(),
            "price": fast.get("lastPrice") or info.get("currentPrice"),
            "currency": info.get("currency", "USD"),
            "change_pct": self._safe_pct(info.get("regularMarketChangePercent")),
            "volume": info.get("regularMarketVolume"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        if df.empty:
            return []
        return [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]

    def get_financials(self, ticker: str) -> dict:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "ticker": ticker.upper(),
            "report_date": self._safe_date(info.get("lastFiscalYearEnd")),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": self._safe_pct(info.get("revenueGrowth")),
            "eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe": self._safe_pct(info.get("returnOnEquity")),
            "profit_margins": self._safe_pct(info.get("profitMargins")),
            "earnings_date_next": self._safe_date(info.get("earningsDate")),
            "dividend_yield": self._safe_pct(info.get("dividendYield")),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_market_snapshot(self) -> dict:
        spx = yf.Ticker("^GSPC")
        info = spx.fast_info
        return {
            "index_name": "S&P 500",
            "current": info.get("lastPrice"),
            "change_pct": self._safe_pct(info.get("regularMarketChangePercent")),
            "ytd_change": self._safe_pct(self._calc_ytd(spx)),
        }

    @staticmethod
    def _safe_pct(value) -> Optional[float]:
        if value is None:
            return None
        try:
            v = float(value)
            return round(v, 2) if abs(v) < 100 else v
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_date(value) -> Optional[str]:
        if value is None:
            return None
        try:
            ts = int(value) if not isinstance(value, (int, float)) else value
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            return str(value)[:10]

    @staticmethod
    def _calc_ytd(stock) -> Optional[float]:
        try:
            df = stock.history(period="ytd")
            if len(df) >= 2:
                return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
        except Exception:
            pass
        return None
