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


def test_fetch_cny_rates_uses_one_for_cny_without_network_request(monkeypatch):
    fetch_cny_rates.clear()

    def get(url, timeout):
        raise AssertionError("CNY should not make an FX request")

    monkeypatch.setattr("app.components.currency.requests.get", get)

    assert fetch_cny_rates(("CN",)) == {"CN": 1.0}


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


def test_fetch_cny_rates_reuses_usd_rate_for_crypto_after_request_failure(monkeypatch):
    fetch_cny_rates.clear()
    FX_RATES.clear()
    FX_RATES.update({"US": 7.2})

    def get(url, timeout):
        raise OSError("provider unavailable")

    monkeypatch.setattr("app.components.currency.requests.get", get)

    assert fetch_cny_rates(("CRYPTO",)) == {"CRYPTO": 7.2}
