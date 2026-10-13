"""Brave web search is a fallback, and provider failures stay inside the tool."""

import requests

import agent.tools as tools
from adapters.brave_search import BraveSearchAdapter, freshness_for_days


def test_freshness_windows():
    assert freshness_for_days(None) is None
    assert freshness_for_days(0) is None
    assert freshness_for_days(1) == "pd"
    assert freshness_for_days(7) == "pw"
    assert freshness_for_days(31) == "pm"
    assert freshness_for_days(90) == "py"


def test_search_parses_web_results_and_sends_token(monkeypatch):
    captured = {}

    class FakeResp:
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "web": {
                    "results": [
                        {
                            "title": "Nvidia earnings",
                            "url": "https://example.com/nvda",
                            "description": "x" * 400,
                            "age": "2 hours ago",
                        },
                        {"title": "", "url": ""},
                    ]
                }
            }

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("adapters.brave_search.config.BRAVE_SEARCH_API_KEY", "test-token")
    monkeypatch.setattr("adapters.brave_search.config.BRAVE_SEARCH_BASE_URL", "https://brave.test/search")
    monkeypatch.setattr("adapters.brave_search.requests.get", fake_get)

    result = BraveSearchAdapter().search("英伟达 财报", count=50, days=7)

    assert captured["headers"]["X-Subscription-Token"] == "test-token"
    assert captured["params"]["q"] == "英伟达 财报"
    assert captured["params"]["count"] == 10
    assert captured["params"]["freshness"] == "pw"
    assert captured["params"]["text_decorations"] == "false"
    assert captured["timeout"] == 10
    assert result["source"] == "brave"
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://example.com/nvda"
    assert len(result["results"][0]["description"]) == 280


def test_missing_key_does_not_call_network(monkeypatch):
    called = []
    monkeypatch.setattr("adapters.brave_search.config.BRAVE_SEARCH_API_KEY", "")
    monkeypatch.setattr(
        "adapters.brave_search.requests.get",
        lambda *args, **kwargs: called.append(1),
    )

    result = BraveSearchAdapter().search("苹果")

    assert called == []
    assert result["error"] == "not_configured"
    assert result["results"] == []


def test_web_search_tool_degrades_on_http_error(monkeypatch):
    class Boom:
        def search(self, query, count=5, days=7):
            raise requests.HTTPError("429")

    monkeypatch.setattr(tools, "brave_search", Boom())
    result = tools.web_search.invoke({"query": "腾讯 回购", "days": 1})
    assert result["error"] == "HTTPError"
    assert result["query"] == "腾讯 回购"
    assert result["source"] == "brave"


def test_web_search_is_registered():
    assert "web_search" in [tool.name for tool in tools.ALL_TOOLS]
