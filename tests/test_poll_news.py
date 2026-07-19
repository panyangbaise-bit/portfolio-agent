"""Hourly news poll includes headlines and ticker articles."""

from agent.core import poll_news_for_portfolio


def test_poll_news_for_portfolio_merges_headlines_and_ticker_news(monkeypatch):
    class FakeAdapter:
        def get_headlines(self, limit=10):
            return [{"title": "Fed holds rates", "summary": "macro"}]

        def get_latest_news(self, limit=10):
            return [{"title": "Oil jumps", "summary": "energy"}]

        def search_ticker_news(self, ticker, days=1):
            return [{"title": f"{ticker} beats estimates", "summary": "earnings"}]

    monkeypatch.setattr("agent.core.news_adapter", FakeAdapter())
    items = poll_news_for_portfolio(["AAPL", "QQQ"])

    categories = {i["category"] for i in items}
    assert "headline" in categories
    assert "ticker" in categories
    assert any(i.get("related_ticker") == "AAPL" for i in items)
    titles = [i["title"] for i in items]
    assert "Fed holds rates" in titles
    assert "Oil jumps" in titles
    # Dedup by title
    assert len(titles) == len(set(titles))
