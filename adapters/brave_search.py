"""Brave web search. Supplement when WallStreetCN has no relevant article."""

from typing import Optional

import requests

from config import config

_MAX_COUNT = 10
_SNIPPET_CHARS = 280


def freshness_for_days(days: Optional[int]) -> Optional[str]:
    """Map a lookback window onto Brave's freshness filter.

    Brave accepts pd (24h), pw (7d), pm (31d), and py (365d). A non-positive
    window leaves freshness unset so the query is not time-boxed.
    """
    if days is None or days <= 0:
        return None
    if days <= 1:
        return "pd"
    if days <= 7:
        return "pw"
    if days <= 31:
        return "pm"
    return "py"


class BraveSearchAdapter:
    """Thin client for the Brave web search API."""

    def search(self, query: str, count: int = 5, days: int = 7) -> dict:
        text = (query or "").strip()
        if not text:
            return {
                "query": "",
                "source": "brave",
                "results": [],
                "error": "empty_query",
                "message": "query is empty",
            }
        token = (config.BRAVE_SEARCH_API_KEY or "").strip()
        if not token:
            return {
                "query": text[:400],
                "source": "brave",
                "results": [],
                "error": "not_configured",
                "message": "BRAVE_SEARCH_API_KEY is not set",
            }

        bounded = max(1, min(int(count or 5), _MAX_COUNT))
        params = {
            "q": text[:400],
            "count": bounded,
            "text_decorations": "false",
        }
        freshness = freshness_for_days(days)
        if freshness:
            params["freshness"] = freshness

        resp = requests.get(
            config.BRAVE_SEARCH_BASE_URL,
            params=params,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        web = payload.get("web") if isinstance(payload, dict) else None
        raw_results = web.get("results") if isinstance(web, dict) else None
        results = []
        for item in raw_results or []:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            if not title and not url:
                continue
            description = (item.get("description") or "").replace("\n", " ").strip()
            results.append({
                "title": title,
                "url": url,
                "description": description[:_SNIPPET_CHARS],
                "age": item.get("age") or item.get("page_age") or "",
            })
        return {"query": text[:400], "source": "brave", "results": results}


brave_search = BraveSearchAdapter()
