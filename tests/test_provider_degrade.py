"""Provider failures must degrade to error payloads — never crash a job."""

import agent.tools as tools
from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
from adapters.crypto import CryptoAdapter
from adapters.us_market import USMarketAdapter


class _BoomAdapter:
    def get_price(self, ticker):
        raise ConnectionError("Remote end closed connection without response")

    def get_kline(self, ticker, period="3mo"):
        raise ConnectionError("Remote end closed connection without response")

    def get_financials(self, ticker):
        raise ConnectionError("Remote end closed connection without response")

    def get_fund_info(self, ticker, top_constituents=20):
        raise ConnectionError("Remote end closed connection without response")

    def get_market_snapshot(self):
        raise ConnectionError("Remote end closed connection without response")


class _BoomRegistry:
    def get(self, market):
        return _BoomAdapter()


def test_market_tools_degrade_on_provider_error(monkeypatch):
    monkeypatch.setattr(tools, "adapter_registry", _BoomRegistry())

    price = tools.get_price.invoke({"ticker": "600519", "market": "CN"})
    assert price["error"] == "ConnectionError"

    kline = tools.get_kline.invoke({"ticker": "AAPL", "market": "US"})
    assert kline == []

    fins = tools.get_financials.invoke({"ticker": "AAPL", "market": "US"})
    assert fins["error"] == "ConnectionError"

    fund = tools.get_fund_info.invoke({"ticker": "020357"})
    assert fund["error"] == "ConnectionError"

    snap = tools.get_market_snapshot.invoke({"market": "US"})
    assert snap["error"] == "ConnectionError"


def test_news_tools_degrade_on_provider_error(monkeypatch):
    class BoomNews:
        def search_ticker_news(self, ticker, days=7):
            raise ConnectionError("closed")

        def get_headlines(self, limit=10):
            raise ConnectionError("closed")

        def get_latest_news(self, limit=10):
            raise ConnectionError("closed")

    monkeypatch.setattr(tools, "news_adapter", BoomNews())

    news = tools.search_ticker_news.invoke({"ticker": "苹果", "days": 1})
    assert news["results"] == []

    headlines = tools.get_market_headlines.invoke({})
    assert headlines == []


def test_us_adapter_degrades(monkeypatch):
    class BoomTicker:
        @property
        def fast_info(self):
            raise ConnectionError("yf down")

        @property
        def info(self):
            raise ConnectionError("yf down")

        def history(self, period="3mo"):
            raise ConnectionError("yf down")

    monkeypatch.setattr("adapters.us_market.yf.Ticker", lambda symbol: BoomTicker())
    us = USMarketAdapter()
    assert us.get_price("AAPL")["error"] == "ConnectionError"
    assert us.get_kline("AAPL") == []
    assert us.get_financials("AAPL")["error"] == "ConnectionError"
    assert us.get_market_snapshot()["error"] == "ConnectionError"


def test_hk_adapter_degrades(monkeypatch):
    class BoomTicker:
        @property
        def fast_info(self):
            raise ConnectionError("yf down")

        @property
        def info(self):
            raise ConnectionError("yf down")

        def history(self, period="3mo"):
            raise ConnectionError("yf down")

    monkeypatch.setattr("yfinance.Ticker", lambda symbol: BoomTicker())
    hk = HKMarketAdapter()
    assert hk.get_price("0700.HK")["error"] == "ConnectionError"
    assert hk.get_kline("0700.HK") == []
    assert hk.get_financials("0700.HK")["error"] == "ConnectionError"
    assert hk.get_market_snapshot()["error"] == "ConnectionError"


def test_crypto_adapter_degrades(monkeypatch):
    import adapters.crypto as crypto_mod

    def boom(*args, **kwargs):
        raise ConnectionError("coingecko down")

    monkeypatch.setattr(crypto_mod.cg, "get_price", boom)
    monkeypatch.setattr(crypto_mod.cg, "get_coin_market_chart_by_id", boom)
    monkeypatch.setattr(crypto_mod.cg, "get_coin_by_id", boom)
    monkeypatch.setattr(crypto_mod.cg, "get_global", boom)

    c = CryptoAdapter()
    assert c.get_price("BTC")["error"] == "ConnectionError"
    assert c.get_kline("BTC") == []
    assert c.get_financials("BTC")["error"] == "ConnectionError"
    assert c.get_market_snapshot()["error"] == "ConnectionError"


def test_cn_kline_degrades(monkeypatch):
    def boom(**kwargs):
        raise ConnectionError("eastmoney down")

    monkeypatch.setattr("adapters.cn_market.ak.stock_zh_a_hist", boom)
    monkeypatch.setattr("adapters.cn_market.ak.fund_open_fund_info_em", boom)
    assert CNMarketAdapter().get_kline("600519") == []
    assert CNMarketAdapter().get_kline("020357") == []
