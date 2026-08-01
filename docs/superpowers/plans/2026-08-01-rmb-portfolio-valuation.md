# RMB Portfolio Valuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert USD- and HKD-denominated positions to CNY for dashboard market value, cost, and P&L totals while retaining local currencies for quote columns.

**Architecture:** A new `app/components/currency.py` module owns FX retrieval, cache and error semantics. A pure valuation helper converts position cost and market values to CNY and a pure holdings-row helper keeps presentation testable; the dashboard supplies the same FX snapshot to KPI and table renders.

**Tech Stack:** Python 3.9, `requests`, Streamlit cache, pytest, pandas.

---

## File structure

- Create `app/components/currency.py`: fetch and cache USD/CNY and HKD/CNY values from ExchangeRate-API; preserve the last successful response.
- Create `app/components/portfolio_valuation.py`: pure market-to-CNY mapping and aggregate calculation.
- Modify `app/components/kpi_cards.py`: accept an FX snapshot and calculate all top-level amounts in CNY.
- Modify `app/components/holdings_table.py`: build testable rows with native price/cost symbols and CNY market value.
- Modify `app/views/dashboard.py`: obtain one FX snapshot and pass it to both dashboard components.
- Create `tests/test_currency.py`: test source parsing, CNY local conversion and last-successful fallback.
- Create `tests/test_portfolio_valuation.py`: test cross-currency aggregation and presentation-row formatting.
- Modify `CLAUDE.md`: document the FX source, caching and currency display rules after the implementation is verified.

### Task 1: Currency service

**Files:**
- Create: `tests/test_currency.py`
- Create: `app/components/currency.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.components.currency import (
    FX_RATES,
    currency_for_market,
    fetch_cny_rates,
)


def test_currency_for_market_uses_declared_market_currencies():
    assert currency_for_market("CN") == "CNY"
    assert currency_for_market("US") == "USD"
    assert currency_for_market("CRYPTO") == "USD"
    assert currency_for_market("HK") == "HKD"


def test_fetch_cny_rates_reads_usd_and_hkd_rates(monkeypatch):
    payloads = {
        "USD": {"result": "success", "rates": {"CNY": 7.2}},
        "HKD": {"result": "success", "rates": {"CNY": 0.92}},
    }

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def get(url, timeout):
        base = url.rsplit("/", 1)[-1]
        return Response(payloads[base])

    monkeypatch.setattr("app.components.currency.requests.get", get)
    FX_RATES.clear()
    fetch_cny_rates.clear()

    assert fetch_cny_rates(("US", "HK")) == {"US": 7.2, "HK": 0.92}


def test_fetch_cny_rates_uses_last_successful_rate_after_request_failure(monkeypatch):
    fetch_cny_rates.clear()
    FX_RATES.update({"US": 7.2})

    def get(url, timeout):
        raise OSError("provider unavailable")

    monkeypatch.setattr("app.components.currency.requests.get", get)

    assert fetch_cny_rates(("US",)) == {"US": 7.2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python3 -m pytest tests/test_currency.py -v`

Expected: collection error because `app.components.currency` does not exist.

- [ ] **Step 3: Implement the minimal currency service**

```python
FX_RATES = {}
_MARKET_CURRENCIES = {
    "CN": "CNY", "US": "USD", "CRYPTO": "USD", "HK": "HKD",
}


def currency_for_market(market):
    return _MARKET_CURRENCIES[market.upper()]


def _fetch_rate(base_currency):
    response = requests.get(
        "https://open.er-api.com/v6/latest/{}".format(base_currency),
        timeout=2,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("result") != "success":
        raise ValueError("FX provider returned an unsuccessful response")
    return float(payload["rates"]["CNY"])


@st.cache_data(ttl=60, show_spinner=False)
def fetch_cny_rates(markets):
    rates = {"CN": 1.0}
    for market in {market.upper() for market in markets}:
        if market == "CN":
            continue
        base_currency = currency_for_market(market)
        try:
            rate = _fetch_rate(base_currency)
            FX_RATES[market] = rate
        except Exception:
            rate = FX_RATES.get(market)
        if rate is not None:
            rates[market] = rate
    return rates
```

Use `tuple(sorted(markets))` as the cached public function argument so Streamlit receives a hashable, deterministic cache key. Store only foreign-market rates in `FX_RATES`; CNY is always local.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python3 -m pytest tests/test_currency.py -v`

Expected: 3 passed.

### Task 2: CNY valuation calculations

**Files:**
- Create: `tests/test_portfolio_valuation.py`
- Create: `app/components/portfolio_valuation.py`

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace

from app.components.portfolio_valuation import calculate_portfolio_totals


def test_calculate_portfolio_totals_converts_cost_and_value_to_cny():
    holdings = [
        SimpleNamespace(market="CN", ticker="600519", shares=2, cost_basis=100),
        SimpleNamespace(market="US", ticker="QQQ", shares=3, cost_basis=10),
        SimpleNamespace(market="HK", ticker="0700", shares=4, cost_basis=20),
    ]
    prices = {
        ("CN", "600519"): 110,
        ("US", "QQQ"): 12,
        ("HK", "0700"): 15,
    }

    totals = calculate_portfolio_totals(
        holdings, prices, {"CN": 1.0, "US": 7.0, "HK": 0.9}
    )

    assert totals["cost"] == 482.0
    assert totals["market_value"] == 526.0
    assert totals["pnl"] == 44.0
    assert round(totals["pnl_pct"], 2) == 9.13


def test_calculate_portfolio_totals_returns_none_when_foreign_fx_is_missing():
    holdings = [SimpleNamespace(market="US", ticker="QQQ", shares=1, cost_basis=10)]

    assert calculate_portfolio_totals(holdings, {("US", "QQQ"): 12}, {}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/test_portfolio_valuation.py -v`

Expected: collection error because `app.components.portfolio_valuation` does not exist.

- [ ] **Step 3: Implement the minimal valuation helper**

```python
def calculate_portfolio_totals(holdings, prices, cny_rates):
    total_cost = 0.0
    total_market_value = 0.0
    has_live_data = False

    for holding in holdings:
        market = holding.market.upper()
        rate = cny_rates.get(market)
        if rate is None:
            return None
        price = prices.get((holding.market, holding.ticker))
        if price is None:
            price = holding.cost_basis
        else:
            has_live_data = True
        total_cost += holding.shares * holding.cost_basis * rate
        total_market_value += holding.shares * price * rate

    pnl = total_market_value - total_cost
    return {
        "cost": total_cost,
        "market_value": total_market_value,
        "pnl": pnl,
        "pnl_pct": pnl / total_cost * 100 if total_cost else 0.0,
        "has_live_data": has_live_data,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python3 -m pytest tests/test_portfolio_valuation.py::test_calculate_portfolio_totals_converts_cost_and_value_to_cny -v`

Expected: 2 passed.

### Task 3: Currency-aware holdings rows

**Files:**
- Modify: `tests/test_portfolio_valuation.py`
- Modify: `app/components/holdings_table.py:33-69`

- [ ] **Step 1: Write the failing formatting test**

```python
from app.components.holdings_table import format_quote, format_cny_market_value


def test_quote_symbols_stay_native_while_market_value_is_cny():
    assert format_quote(687.99, "US") == "$687.9900"
    assert format_quote(590.53, "CRYPTO") == "$590.5300"
    assert format_quote(3.1935, "CN") == "¥3.1935"
    assert format_quote(134.81, "HK") == "HK$134.8100"
    assert format_cny_market_value(4960.89) == "¥4,960.89"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/test_portfolio_valuation.py::test_quote_symbols_stay_native_while_market_value_is_cny -v`

Expected: import error because the formatting helpers do not exist.

- [ ] **Step 3: Implement helpers and use CNY market value**

```python
_CURRENCY_SYMBOLS = {
    "CN": "¥", "US": "$", "CRYPTO": "$", "HK": "HK$",
}


def format_quote(value, market):
    return "{}{:.4f}".format(_CURRENCY_SYMBOLS[market.upper()], value)


def format_cny_market_value(value):
    return "¥{:,.2f}".format(value)
```

Extract the existing `rows` loop into `build_holding_rows(holdings, prices, cny_rates)`. Preserve P&L percentage calculation in original currency. If the required market FX rate is missing, set that row's Market Value to `"—"`; do not display the unconverted amount. Make `render_holdings_table` accept `cny_rates` and call this helper before building the dataframe.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python3 -m pytest tests/test_portfolio_valuation.py -v`

Expected: 3 passed.

### Task 4: Share the FX snapshot across dashboard KPI and table

**Files:**
- Modify: `app/components/kpi_cards.py:7-65`
- Modify: `app/views/dashboard.py:9-65`

- [ ] **Step 1: Wire the snapshot into the render path**

```python
# app/views/dashboard.py
cny_rates = fetch_cny_rates(tuple(sorted({holding.market for holding in holdings})))
render_kpi_cards(holdings=holdings, prices=prices, cny_rates=cny_rates)
render_holdings_table(holdings=holdings, prices=prices, cny_rates=cny_rates)
```

```python
# app/components/kpi_cards.py
totals = calculate_portfolio_totals(holdings, prices, cny_rates)
if totals is None:
    st.warning("FX rates are unavailable; RMB portfolio totals cannot be calculated.")
else:
    st.metric(t("kpi.total_value"), "¥{:,.2f}".format(totals["market_value"]), ...)
```

Use an i18n key for the warning in both English and Chinese, rather than placing the shown English sentence directly in the component. Keep the existing label choice based on `totals["has_live_data"]`.

- [ ] **Step 2: Run focused tests to verify they pass**

Run: `PYTHONPATH=. python3 -m pytest tests/test_currency.py tests/test_portfolio_valuation.py tests/test_price_fetcher.py tests/test_price_snapshot.py -v`

Expected: all focused tests pass.

### Task 5: Document and verify the completed change

**Files:**
- Modify: `CLAUDE.md:46-60`

- [ ] **Step 1: Update the architecture and gotchas documentation**

Add a concise `Currency conversion` gotcha stating that `app/components/currency.py` requests USD/CNY and HKD/CNY through ExchangeRate-API, caches results for 60 seconds, uses the process-local last successful rate on transient errors, and makes Market Value/KPI totals CNY while Cost and Price retain native symbols.

- [ ] **Step 2: Run lint diagnostics**

Run: use the IDE linter check for `app/components/currency.py`, `app/components/portfolio_valuation.py`, `app/components/kpi_cards.py`, and `app/components/holdings_table.py`.

Expected: no new diagnostics.

- [ ] **Step 3: Run complete regression suite**

Run: `PYTHONPATH=. python3 -m pytest tests -v`

Expected: all tests pass.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check && git diff -- app/components/currency.py app/components/portfolio_valuation.py app/components/kpi_cards.py app/components/holdings_table.py app/views/dashboard.py tests/test_currency.py tests/test_portfolio_valuation.py CLAUDE.md`

Expected: no whitespace errors; only the planned currency-conversion changes.
