"""A-share spot board should be reused within the TTL window."""

import pandas as pd

import adapters.cn_market as cn_market
from adapters.cn_market import CNMarketAdapter


def test_a_share_spot_df_cached_within_ttl(monkeypatch):
    calls = {"n": 0}
    df = pd.DataFrame(
        [
            {"代码": "600519", "最新价": 1600.0, "涨跌幅": 1.0, "成交量": 100},
            {"代码": "300750", "最新价": 200.0, "涨跌幅": -0.5, "成交量": 200},
        ]
    )

    def fake_spot():
        calls["n"] += 1
        return df

    monkeypatch.setattr(cn_market, "_spot_df", None)
    monkeypatch.setattr(cn_market, "_spot_fetched_at", 0.0)
    monkeypatch.setattr(cn_market.ak, "stock_zh_a_spot_em", fake_spot)

    adapter = CNMarketAdapter()
    a = adapter.get_price("600519")
    b = adapter.get_price("300750")

    assert calls["n"] == 1
    assert a["price"] == 1600.0
    assert b["price"] == 200.0


def test_a_share_spot_uses_stale_cache_when_refresh_fails(monkeypatch):
    df = pd.DataFrame(
        [{"代码": "600519", "最新价": 1600.0, "涨跌幅": 1.0, "成交量": 100}]
    )
    calls = {"n": 0}

    def fail_then_ok():
        calls["n"] += 1
        if calls["n"] == 1:
            return df
        raise ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(cn_market, "_spot_df", None)
    monkeypatch.setattr(cn_market, "_spot_fetched_at", 0.0)
    monkeypatch.setattr(cn_market, "_SPOT_TTL_SECONDS", 0.0)
    monkeypatch.setattr(cn_market.ak, "stock_zh_a_spot_em", fail_then_ok)

    adapter = CNMarketAdapter()
    first = adapter.get_price("600519")
    second = adapter.get_price("600519")
    assert first["price"] == 1600.0
    assert second["price"] == 1600.0
    assert calls["n"] == 2


def test_a_share_spot_returns_error_when_no_cache(monkeypatch):
    def boom():
        raise ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(cn_market, "_spot_df", None)
    monkeypatch.setattr(cn_market, "_spot_fetched_at", 0.0)
    monkeypatch.setattr(cn_market.ak, "stock_zh_a_spot_em", boom)

    out = CNMarketAdapter().get_price("600519")
    assert out["error"] == "ConnectionError"
    assert "closed connection" in out["message"]
