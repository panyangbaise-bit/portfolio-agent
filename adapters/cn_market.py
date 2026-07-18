from datetime import datetime
from typing import Optional
import akshare as ak

from adapters.base import MarketAdapter


class CNMarketAdapter(MarketAdapter):
    """A-share market data via akshare."""

    MARKET = "CN"

    def get_price(self, ticker: str) -> dict:
        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == ticker]
            if row.empty:
                raise ValueError(f"Ticker {ticker} not found")
            r = row.iloc[0]
            return {
                "ticker": ticker,
                "price": float(r["最新价"]),
                "currency": "CNY",
                "change_pct": float(r["涨跌幅"]),
                "volume": float(r["成交量"]) if "成交量" in r else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get CN price for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        mapping = {"1mo": "monthly", "3mo": "quarterly", "6mo": "halfyear", "1y": "yearly", "5y": "yearly"}
        freq = mapping.get(period, "daily")
        try:
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
        except Exception as e:
            raise RuntimeError(f"Failed to get CN kline for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        try:
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
        except Exception as e:
            return {"ticker": ticker, "error": str(e)}

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
    """Hong Kong market data via akshare."""

    MARKET = "HK"

    def get_price(self, ticker: str) -> dict:
        try:
            df = ak.stock_hk_spot_em()
            row = df[df["代码"] == ticker]
            if row.empty:
                raise ValueError(f"Ticker {ticker} not found")
            r = row.iloc[0]
            return {
                "ticker": ticker,
                "price": float(r["最新价"]),
                "currency": "HKD",
                "change_pct": float(r["涨跌幅"]),
                "volume": float(r["成交量"]) if "成交量" in r else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get HK price for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        try:
            df = ak.stock_hk_hist(symbol=ticker, period="daily", adjust="qfq")
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
        except Exception as e:
            raise RuntimeError(f"Failed to get HK kline for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        return {"ticker": ticker, "note": "HK financials via akshare limited; use manual input or alternative source"}

    def get_market_snapshot(self) -> dict:
        try:
            df = ak.stock_hk_index_daily_em()
            if df.empty:
                return {"index_name": "恒生指数", "error": "no data"}
            latest = df.iloc[-1]
            return {
                "index_name": "恒生指数",
                "current": float(latest.get("close", 0) or latest.get("收盘", 0)),
            }
        except Exception as e:
            return {"index_name": "恒生指数", "error": str(e)}
