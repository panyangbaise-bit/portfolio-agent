"""Regressions from the October 19 traces: wrong identities and false absence."""

import pandas as pd
import pytest

from a2a.queries import read_query
from adapters.cn_market import CNMarketAdapter
from adapters.news import WallStreetCNAdapter
from agent.kline import enrich_kline
from domain.instruments import resolve_cn_symbol


def test_bare_index_code_cannot_silently_return_fund_nav(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("ambiguous symbol reached a provider")

    monkeypatch.setattr(CNMarketAdapter, "_get_fund_kline", forbidden)
    monkeypatch.setattr(CNMarketAdapter, "_get_stock_kline", forbidden)
    result = CNMarketAdapter().get_kline("000688")
    assert result["error"] == "ValueError"
    assert "index:000688" in result["message"]
    assert CNMarketAdapter().get_price("000688")["error"] == "ValueError"


def test_explicit_index_uses_index_provider_and_exposes_identity(monkeypatch):
    calls = []

    def history(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "日期": "2026-10-19",
                    "开盘": 1000,
                    "收盘": 1010,
                    "最高": 1020,
                    "最低": 990,
                    "成交量": 100,
                }
            ]
        )

    monkeypatch.setattr("adapters.cn_market.ak.index_zh_a_hist", history)
    rows = CNMarketAdapter().get_kline("INDEX:000688", "1mo")
    assert calls[0]["symbol"] == "000688"
    assert rows[0]["asset_type"] == "index"
    assert rows[0]["resolved_code"] == "000688"
    assert rows[0]["series_kind"] == "ohlc"
    assert rows[0]["close"] == 1010


def test_stock_provider_error_never_falls_back_to_a_different_fund(monkeypatch):
    def failure(*args):
        raise ValueError("not found")

    monkeypatch.setattr(CNMarketAdapter, "_get_stock_kline", failure)
    monkeypatch.setattr(CNMarketAdapter, "_get_fund_kline", lambda *a: pytest.fail("fallback"))
    assert CNMarketAdapter().get_kline("stock:000001")["error"] == "ValueError"
    assert resolve_cn_symbol("020357") == ("fund", "020357")
    assert resolve_cn_symbol("510050") == ("etf", "510050")


def test_nav_rejects_accidental_volume_and_states_unknown_conditions():
    result = enrich_kline(
        [{"date": "2026-10-16", "close": 1.084, "volume": 999, "series_kind": "nav"}], "CN"
    )
    assert result[0]["volume"] is None
    assert result[0]["volume_ratio5"] is None
    assert "无法判断" in result[0]["analysis_limitations"]


def test_ledger_rejects_unsupported_batch_before_querying():
    with pytest.raises(ValueError, match="one symbol"):
        read_query("transactions", {"ticker": "020357,011613"})


def test_news_outage_is_not_an_empty_success(monkeypatch):
    def failure(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr("adapters.news.requests.get", failure)
    with pytest.raises(ConnectionError):
        WallStreetCNAdapter().search_ticker_news("多邻国")


def test_news_timestamps_are_aware_utc():
    row = WallStreetCNAdapter._parse_items([{"title": "news", "display_time": 1}])[0]
    assert row["published_at"] == "1970-01-01T00:00:01+00:00"
