"""CN OTC fund NAV quotes must expose T+1 / nav_date metadata."""

from adapters.cn_market import CNMarketAdapter


class _FakeDF:
    def __init__(self, rows):
        self._rows = rows
        self.empty = len(rows) == 0

    def __len__(self):
        return len(self._rows)

    @property
    def iloc(self):
        return self

    def __getitem__(self, idx):
        return self._rows[idx]


def test_get_fund_price_labels_nav_t1(monkeypatch):
    rows = [
        {"单位净值": 3.10, "净值日期": "2026-07-31"},
        {"单位净值": 3.1935, "净值日期": "2026-08-01"},
    ]
    monkeypatch.setattr(
        "adapters.cn_market.ak.fund_open_fund_info_em",
        lambda symbol, indicator: _FakeDF(rows),
    )

    quote = CNMarketAdapter()._get_fund_price("020357")

    assert quote["price"] == 3.1935
    assert quote["nav_date"] == "2026-08-01"
    assert quote["prev_nav_date"] == "2026-07-31"
    assert quote["quote_type"] == "nav"
    assert quote["lag"] == "T+1"
    assert quote["change_pct_basis"] == "nav_dod"
    assert quote["timestamp"] == "2026-08-01"
    assert quote["change_pct"] == round((3.1935 / 3.10 - 1) * 100, 2)
    assert "T+1" in quote["note"]
