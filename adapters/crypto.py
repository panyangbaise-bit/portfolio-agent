from datetime import datetime
from typing import Optional
from pycoingecko import CoinGeckoAPI
import requests

from adapters.base import MarketAdapter


cg = CoinGeckoAPI()

# Short timeout for API calls — fail fast, don't block dashboard
cg.session.timeout = 10
cg.session.headers.update({"User-Agent": "portfolio-agent/1.0"})

TICKER_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
}


class CryptoAdapter(MarketAdapter):
    """Crypto data via CoinGecko free API."""

    MARKET = "CRYPTO"

    def _get_id(self, ticker: str) -> str:
        return TICKER_TO_ID.get(ticker.upper(), ticker.lower())

    def get_price(self, ticker: str) -> dict:
        coin_id = self._get_id(ticker)
        try:
            data = cg.get_price(
                ids=coin_id,
                vs_currencies="usd",
                include_market_cap=True,
                include_24hr_vol=True,
                include_24hr_change=True,
            )
            info = data.get(coin_id, {})
            return {
                "ticker": ticker.upper(),
                "price": info.get("usd"),
                "currency": "USD",
                "change_pct": round(info.get("usd_24h_change", 0), 2),
                "volume": info.get("usd_24h_vol"),
                "market_cap": info.get("usd_market_cap"),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"CoinGecko price failed for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        coin_id = self._get_id(ticker)
        days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "5y": 1825}
        days = days_map.get(period, 90)
        try:
            data = cg.get_coin_market_chart_by_id(id=coin_id, vs_currency="usd", days=days)
            prices = data.get("prices", [])
            total_volumes = data.get("total_volumes", [])
            return [
                {
                    "date": datetime.fromtimestamp(p[0] / 1000).strftime("%Y-%m-%d"),
                    "price": p[1],
                    "volume": total_volumes[i][1] if i < len(total_volumes) else None,
                }
                for i, p in enumerate(prices)
                if i % max(1, len(prices) // 100) == 0
            ]
        except Exception as e:
            raise RuntimeError(f"CoinGecko kline failed for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        coin_id = self._get_id(ticker)
        try:
            data = cg.get_coin_by_id(id=coin_id)
            market = data.get("market_data", {})
            return {
                "ticker": ticker.upper(),
                "name": data.get("name", coin_id),
                "market_cap": market.get("market_cap", {}).get("usd"),
                "total_volume": market.get("total_volume", {}).get("usd"),
                "fdv": market.get("fully_diluted_valuation", {}).get("usd"),
                "circulating_supply": market.get("circulating_supply"),
                "total_supply": market.get("total_supply"),
                "max_supply": market.get("max_supply"),
                "ath": market.get("ath", {}).get("usd"),
                "ath_change_pct": round(market.get("ath_change_percentage", {}).get("usd", 0), 2),
                "genesis_date": data.get("genesis_date"),
                "categories": data.get("categories", [])[:5],
            }
        except Exception as e:
            return {"ticker": ticker.upper(), "error": str(e)}

    def get_market_snapshot(self) -> dict:
        try:
            data = cg.get_global()
            mkt = data.get("data", {})
            return {
                "index_name": "Crypto Total Market",
                "current": mkt.get("total_market_cap", {}).get("usd"),
                "change_pct": round(mkt.get("market_cap_change_percentage_24h_usd", 0), 2),
                "btc_dominance": round(mkt.get("market_cap_percentage", {}).get("btc", 0), 2),
                "active_cryptocurrencies": mkt.get("active_cryptocurrencies"),
            }
        except Exception as e:
            return {"index_name": "Crypto Market", "error": str(e)}
