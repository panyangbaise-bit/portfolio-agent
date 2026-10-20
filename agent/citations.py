"""Ground report citations in retrieved sources and persist portable Markdown."""

import hashlib
import html
import re
from urllib.parse import quote, urlsplit

from agent.research import canonical_news_url

CITATION_TOKEN = re.compile(r"\[\[cite:([^\]\s]+)\]\]")
SOURCE_TOOLS = {"search_ticker_news", "get_market_headlines", "web_search"}


def safe_source_url(value):
    """Only external HTTP(S) links; never turn model text into executable URLs."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if any(ord(char) < 32 for char in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        parsed.port  # Reject malformed ports as well.
    except ValueError:
        return None
    return quote(value, safe=":/?#[]@!$&'()*+,;=%~-")


def _plain(value, limit):
    text = html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))
    return " ".join(text.split())[:limit]


def annotate_sources(payload, sources):
    """Copy nested news/search results, adding source tokens to usable records."""
    if isinstance(payload, list):
        return [annotate_sources(item, sources) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = {key: annotate_sources(value, sources) for key, value in payload.items()}
    url = safe_source_url(payload.get("url"))
    if url and payload.get("title"):
        ident = hashlib.sha256(canonical_news_url(url).encode()).hexdigest()[:16]
        source = {
            "url": url,
            "title": _plain(payload["title"], 180),
            "summary": _plain(payload.get("summary") or payload.get("description"), 320),
            "published_at": payload.get("published_at"),
            "fetched_at": payload.get("fetched_at"),
            "evidence_level": "snippet"
            if payload.get("summary") or payload.get("description")
            else "title_only",
        }
        # Keep the first snapshot, but allow a later retrieval to fill an empty summary.
        if ident not in sources or not sources[ident].get("summary"):
            sources[ident] = source
        result["citation"] = f"[[cite:{ident}]]"
    return result


def resolve_citations(content, sources):
    """Number citations by first use, using only metadata observed by the agent.

    Standard Markdown links preserve their tooltip, even across chart blocks or
    when the report is reopened from history, without allowing raw report HTML.
    """
    if not isinstance(content, str):
        return content
    numbers = {}

    def replace(match):
        ident = match.group(1)
        source = sources.get(ident)
        url = safe_source_url(source.get("url")) if source else None
        if not url:
            return "[来源不可用]"
        number = numbers.setdefault(ident, len(numbers) + 1)
        title = _plain(source.get("title"), 180)
        summary = _plain(source.get("summary"), 320)
        tooltip = f"[{number}] {title}" + (f" — {summary}" if summary else "")
        # Attribute entities cannot break Markdown's quoted title or table cells.
        tooltip = html.escape(tooltip, quote=True).replace("|", "&#124;")
        tooltip = tooltip.replace("\\", "&#92;")
        return f'[\\[{number}\\]](<{url}> "{tooltip}")'

    return CITATION_TOKEN.sub(replace, content)
