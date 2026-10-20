"""Evidence coverage, canonical identities and bounded search escalation."""

import json
import re
from urllib.parse import urlsplit, urlunsplit

# One identity per company prevents Chinese/English retries spending the budget twice.
NEWS_IDENTITIES = {
    "DUOL": ("多邻国", "Duolingo DUOL investor relations earnings news"),
    "QQQ": ("纳斯达克", "Nasdaq 100 QQQ market news"),
    "AAPL": ("苹果", "Apple AAPL investor relations news"),
    "NVDA": ("英伟达", "NVIDIA NVDA investor relations news"),
    "MSFT": ("微软", "Microsoft MSFT investor relations news"),
    "TSLA": ("特斯拉", "Tesla TSLA investor relations news"),
    "0700": ("腾讯", "Tencent investor relations announcements"),
}


def news_identity(query):
    text = query.strip()
    for ticker, (chinese, english) in NEWS_IDENTITIES.items():
        if (
            text.upper() == ticker
            or text == chinese
            or text.casefold() == english.split()[0].casefold()
        ):
            return ticker, chinese, english
    return text.casefold(), text, f"{text} official announcement latest news"


def canonical_news_url(url):
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return str(url or "")
    # WSCN keyword/layout query parameters do not identify different articles.
    if parts.hostname == "wallstreetcn.com":
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return str(url or "")


def current_turn(messages):
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            return messages[i:]
    return messages


def verification_plan(messages, budget=2, coverage_gaps=()):
    """Guarantee one cross-source lookup for uncovered ticker searches.

    Run before the next model call. This is a bounded discovery step, not proof
    that snippets verify a claim. All attempts, including failures, count.
    """
    messages = current_turn(messages)
    calls = {c["id"]: c for m in messages for c in getattr(m, "tool_calls", [])}
    searched = set()
    attempts = 0
    for call in calls.values():
        if call["name"] == "web_search":
            attempts += 1
            searched.add(call["args"].get("query", "").casefold())
    if attempts >= budget:
        return []
    gaps = {}
    if any(getattr(m, "type", None) == "tool" for m in messages):
        for query in coverage_gaps:
            identity, _, english = news_identity(query)
            if not any(identity.casefold() in q or english.casefold() in q for q in searched):
                gaps[identity] = {
                    "query": english,
                    "days": 7,
                    "count": 5,
                    "reason": "poll_coverage_gap",
                }
    for msg in messages:
        if getattr(msg, "name", None) != "search_ticker_news":
            continue
        try:
            payload = json.loads(msg.content)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        args = calls.get(msg.tool_call_id, {}).get("args", {})
        results = payload.get("results")
        groups = (
            results
            if payload.get("batch") and isinstance(results, dict)
            else {payload.get("ticker") or args.get("ticker", ""): results}
        )
        for query, rows in groups.items():
            if not query:
                continue
            identity, _, english = news_identity(query)
            # Even a populated single publisher search cannot corroborate a material claim.
            if not isinstance(rows, list) or not rows:
                reason = "no_results_or_error"
            elif any(not r.get("summary") or not r.get("published_at") for r in rows):
                reason = "missing_summary_or_date"
            else:
                continue
            if english.casefold() in searched or any(
                re.search(r"(?<!\w)" + re.escape(identity.casefold()) + r"(?!\w)", q)
                for q in searched
            ):
                continue
            gaps[identity] = {
                "query": english,
                "days": max(7, args.get("days", 7)),
                "count": 5,
                "reason": reason,
            }
    # Known securities first; broad macro synonyms must not crowd out companies.
    selected = sorted(
        gaps.values(),
        key=lambda g: (
            g["query"] not in {v[1] for v in NEWS_IDENTITIES.values()},
            g["reason"] == "missing_summary_or_date",
        ),
    )[: budget - attempts]
    return [{**g, "query": g["query"] + " -site:wallstreetcn.com"} for g in selected]


def select_news(items, limit=20):
    """Keep coverage failures and holding-specific news ahead of generic headlines."""
    selected = []
    seen = set()
    for item in sorted(items, key=lambda x: {"coverage": 0, "ticker": 1}.get(x.get("category"), 2)):
        key = canonical_news_url(item.get("url")) or item.get("title")
        if not key:
            continue
        if key in seen:
            previous = next(
                n for n in selected if (canonical_news_url(n.get("url")) or n.get("title")) == key
            )
            for field in ("summary", "published_at"):
                if not previous.get(field) and item.get(field):
                    previous[field] = item[field]
            continue
        seen.add(key)
        selected.append(dict(item))
    return selected[:limit]
