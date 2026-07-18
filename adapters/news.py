from datetime import datetime, timezone
import requests

from config import config


class WallStreetCNAdapter:
    """News adapter for 华尔街见闻 API."""

    BASE = config.WALLSTREETCN_BASE_URL

    def get_headlines(self, limit: int = 10) -> list[dict]:
        """Top carousel headlines."""
        url = f"{self.BASE}/content/carousel/information-flow"
        try:
            resp = requests.get(url, params={"channel": "global", "limit": limit}, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("data", {}) or {}
            items = items.get("items", [])
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] headlines fetch failed: {e}")
            return []

    def get_latest_news(self, limit: int = 10) -> list[dict]:
        """Latest information flow."""
        url = f"{self.BASE}/content/information-flow"
        try:
            resp = requests.get(
                url, params={"channel": "global", "accept": "article", "limit": limit}, timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("data", {}) or {}
            items = items.get("items", [])
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] latest fetch failed: {e}")
            return []

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search articles by keyword (use ticker or Chinese name)."""
        url = f"{self.BASE}/search/article"
        try:
            resp = requests.get(url, params={"query": query, "limit": limit}, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            if data is None:
                return []
            items = data.get("items", [])
            if items is None:
                return []
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] search failed for '{query}': {e}")
            return []

    def get_hot_articles(self) -> list[dict]:
        """Trending hot articles."""
        url = f"{self.BASE}/content/articles/hot"
        try:
            resp = requests.get(url, params={"period": "all"}, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("day_items", [])
            return self._parse_items(items, is_hot=True)
        except Exception as e:
            print(f"[news] hot articles failed: {e}")
            return []

    def search_ticker_news(self, ticker: str, days: int = 7) -> list[dict]:
        """Search news for a specific ticker."""
        results = self.search(query=ticker, limit=5)
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        filtered = []
        for r in results:
            pub = r.get("published_at")
            if pub is None:
                continue
            try:
                pub_ts = datetime.fromisoformat(pub).timestamp() if isinstance(pub, str) else float(pub)
            except (ValueError, TypeError):
                continue
            if pub_ts >= cutoff:
                filtered.append(r)
        return filtered

    @staticmethod
    def _parse_items(items: list, is_hot: bool = False) -> list[dict]:
        parsed = []
        for item in (items or []):
            resource = item if is_hot else item.get("resource", item)
            if resource is None:
                continue
            ts = resource.get("display_time", 0)
            parsed.append({
                "title": resource.get("title", ""),
                "uri": resource.get("uri", ""),
                "url": f"https://wallstreetcn.com/articles/{resource.get('uri', '')}" if resource.get("uri") else "",
                "summary": (resource.get("content_short") or "")[:200],
                "published_at": datetime.fromtimestamp(ts).isoformat() if ts else None,
                "author": (resource.get("author") or {}).get("display_name", ""),
            })
        return parsed


# Singleton
news_adapter = WallStreetCNAdapter()
