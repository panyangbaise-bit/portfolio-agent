from app.components.price_fetcher import overlay_live_prices, resolve_display_price


def test_live_prices_replace_cached_prices_only_when_available():
    cached = {
        ("US", "QQQ"): 640.0,
        ("CRYPTO", "BTC"): 60000.0,
    }
    live = {
        ("US", "QQQ"): 695.0,
        ("CRYPTO", "BTC"): None,
    }

    assert overlay_live_prices(cached, live) == {
        ("US", "QQQ"): 695.0,
        ("CRYPTO", "BTC"): 60000.0,
    }


def test_missing_price_uses_cost_basis_for_complete_portfolio_metrics():
    assert resolve_display_price(None, 123.45) == 123.45
