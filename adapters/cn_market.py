from datetime import datetime
from typing import Optional
import akshare as ak

from adapters.base import MarketAdapter


class CNMarketAdapter(MarketAdapter):
    """A-share market data via akshare. Supports stocks and funds/ETFs."""

    MARKET = "CN"

    @staticmethod
    def _is_fund(ticker: str) -> bool:
        """Detect fund codes: 6-digit numeric codes (ETF联接, LOF, etc.)."""
        return ticker.isdigit() and len(ticker) == 6

    def get_price(self, ticker: str) -> dict:
        # For fund-like codes (starting with 0), try fund API directly
        if self._is_fund(ticker) and ticker[0] == "0":
            return self._get_fund_price(ticker)
        # For stock-like codes, try stock API first
        try:
            return self._get_stock_price(ticker)
        except ValueError:
            if self._is_fund(ticker):
                return self._get_fund_price(ticker)
            raise

    def _get_stock_price(self, ticker: str) -> dict:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == ticker]
        if row.empty:
            raise ValueError(f"Ticker {ticker} not found in stock list")
        r = row.iloc[0]
        return {
            "ticker": ticker,
            "price": float(r["最新价"]),
            "currency": "CNY",
            "change_pct": float(r["涨跌幅"]),
            "volume": float(r["成交量"]) if "成交量" in r else None,
            "timestamp": datetime.now().isoformat(),
        }

    def _get_fund_price(self, ticker: str) -> dict:
        df = ak.fund_open_fund_info_em(symbol=ticker, indicator="单位净值走势")
        if df.empty:
            raise ValueError(f"Fund {ticker} not found")
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        change_pct = 0.0
        if latest["单位净值"] and prev["单位净值"]:
            change_pct = round((float(latest["单位净值"]) / float(prev["单位净值"]) - 1) * 100, 2)
        return {
            "ticker": ticker,
            "price": float(latest["单位净值"]),
            "currency": "CNY",
            "change_pct": change_pct,
            "volume": None,
            "timestamp": datetime.now().isoformat(),
        }

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        if self._is_fund(ticker) and ticker[0] == "0":
            return self._get_fund_kline(ticker, period)
        try:
            return self._get_stock_kline(ticker, period)
        except (ValueError, KeyError):
            if self._is_fund(ticker):
                return self._get_fund_kline(ticker, period)
            raise

    def _get_stock_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        mapping = {"1mo": "monthly", "3mo": "quarterly", "6mo": "halfyear", "1y": "yearly", "5y": "yearly"}
        freq = mapping.get(period, "daily")
        df = ak.stock_zh_a_hist(symbol=ticker, period=freq, adjust="qfq")
        if df.empty:
            return []
        return [
            {
                "date": str(row["日期"])[:10],
                "open": float(row["开盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "close": float(row["收盘"]),
                "volume": float(row["成交量"]) if "成交量" in row else None,
            }
            for _, row in df.tail(90).iterrows()
        ]

    def _get_fund_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        days_map = {"1mo": 22, "3mo": 66, "6mo": 132, "1y": 252, "5y": 1260}
        limit = days_map.get(period, 66)
        df = ak.fund_open_fund_info_em(symbol=ticker, indicator="单位净值走势")
        if df.empty:
            return []
        df = df.tail(limit)
        return [
            {
                "date": str(row["净值日期"])[:10],
                "open": float(row["单位净值"]),
                "high": float(row["单位净值"]),
                "low": float(row["单位净值"]),
                "close": float(row["单位净值"]),
                "volume": None,
            }
            for _, row in df.iterrows()
        ]

    def get_financials(self, ticker: str) -> dict:
        if self._is_fund(ticker) and not self._ticker_looks_like_stock(ticker):
            return {"ticker": ticker, "note": "基金产品，无财报数据。关注净值走势和基金持仓。"}
        try:
            return self._get_stock_financials(ticker)
        except Exception:
            return {"ticker": ticker, "note": "no financial data available"}

    @staticmethod
    def _ticker_looks_like_stock(ticker: str) -> bool:
        """Stock codes start with 0/3/6; pure fund codes start with 0/1/5.
        But there's overlap, so we try stock first and only treat as fund
        if the code explicitly fails stock lookup."""
        return ticker[0] in ("6", "0", "3") and len(ticker) == 6

    def _get_stock_financials(self, ticker: str) -> dict:
        df = ak.stock_financial_abstract_ths(symbol=ticker, indicator="按报告期")
        if df.empty:
            return {"ticker": ticker, "note": "no financial data available"}
        latest = df.iloc[0]
        return {
            "ticker": ticker,
            "report_date": str(latest.get("报告期", ""))[:10],
            "revenue": self._safe_float(latest.get("营业总收入")),
            "revenue_growth": self._safe_float(latest.get("营业总收入同比增长")),
            "eps": self._safe_float(latest.get("基本每股收益")),
            "roe": self._safe_float(latest.get("净资产收益率")),
            "profit_margin": self._safe_float(latest.get("销售净利率")),
        }

    def get_market_snapshot(self) -> dict:
        try:
            df = ak.stock_zh_index_daily(symbol="sh000001")
            if df.empty:
                return {"index_name": "上证指数", "error": "no data"}
            latest = df.iloc[-1]
            return {
                "index_name": "上证指数",
                "current": float(latest["close"]),
                "change_pct": round(float(latest.get("pct_chg", 0)), 2),
            }
        except Exception as e:
            return {"index_name": "上证指数", "error": str(e)}

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None or value == "" or value == "--":
            return None
        try:
            return round(float(value), 2)
        except (ValueError, TypeError):
            return None


class HKMarketAdapter(MarketAdapter):
    """Hong Kong market data via yfinance.

    Ticker conversion: "02026.HK" or "02026" → strip .HK → strip leading
    zeros → append .HK → "2026.HK" (yfinance format).
    """

    MARKET = "HK"

    @staticmethod
    def _to_yf_ticker(ticker: str) -> str:
        """Convert user ticker to yfinance HK format.

        "02026.HK" → "2026.HK", "00700.HK" → "0700.HK"
        """
        t = ticker.upper().replace(".HK", "").lstrip("0")
        return f"{t}.HK"

    @staticmethod
    def _safe_pct(value) -> Optional[float]:
        if value is None:
            return None
        try:
            v = float(value)
            return round(v, 2) if abs(v) < 100 else v
        except (ValueError, TypeError):
            return None

    def get_price(self, ticker: str) -> dict:
        import yfinance as yf
        symbol = self._to_yf_ticker(ticker)
        stock = yf.Ticker(symbol)
        fast = stock.fast_info
        price = fast.get("lastPrice")
        if price is None:
            # Avoid the slow metadata endpoint unless the fast quote is empty.
            info = stock.info
            price = info.get("currentPrice")
        if price is None:
            raise ValueError(f"No price data for {symbol}")
        return {
            "ticker": ticker.upper().replace(".HK", ""),
            "price": float(price),
            "currency": "HKD",
            "change_pct": None,
            "volume": None,
            "timestamp": datetime.now().isoformat(),
        }

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        import yfinance as yf
        symbol = self._to_yf_ticker(ticker)
        stock = yf.Ticker(symbol)
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
        import yfinance as yf
        symbol = self._to_yf_ticker(ticker)
        stock = yf.Ticker(symbol)
        info = stock.info
        return {
            "ticker": ticker.upper().replace(".HK", ""),
            "name": info.get("longName") or info.get("shortName"),
            "report_date": str(info.get("lastFiscalYearEnd", ""))[:10] if info.get("lastFiscalYearEnd") else None,
            "revenue": info.get("totalRevenue"),
            "revenue_growth": self._safe_pct(info.get("revenueGrowth")),
            "eps": info.get("trailingEps"),
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "roe": self._safe_pct(info.get("returnOnEquity")),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_market_snapshot(self) -> dict:
        import yfinance as yf
        hsi = yf.Ticker("^HSI")
        info = hsi.fast_info
        return {
            "index_name": "恒生指数",
            "current": info.get("lastPrice"),
            "change_pct": self._safe_pct(getattr(info, "regularMarketChangePercent", None)),
        }
