"""Source-grounded citations survive generation, storage and report rendering."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.citations import annotate_sources, resolve_citations, safe_source_url


def article(**changes):
    return {"title": "公司财报", "url": "https://example.com/earnings?a=1&b=2",
            "summary": "收入增长，但利润率下降。", **changes}


def test_batch_sources_are_deduplicated_without_mutating_results():
    original = {"batch": True, "results": {"AAPL": [article()], "MSFT": [article()]}}
    sources = {}
    result = annotate_sources(original, sources)
    assert len(sources) == 1
    assert "citation" not in original["results"]["AAPL"][0]
    token = result["results"]["AAPL"][0]["citation"]
    assert token == result["results"]["MSFT"][0]["citation"]
    report = resolve_citations(f"收入增长{token}。利润承压{token}。", sources)
    assert report.count('[\\[1\\]](') == 2
    assert "收入增长，但利润率下降。" in report
    assert '(<https://example.com/earnings?a=1&b=2>' in report


def test_first_appearance_numbering_and_brave_description():
    sources = {}
    first, second = annotate_sources([
        article(), article(url="https://example.com/other", summary="", description="网页摘要"),
    ], sources)
    text = resolve_citations(second["citation"] + first["citation"], sources)
    assert text.startswith('[\\[1\\]](<https://example.com/other>')
    assert '[\\[2\\]](<https://example.com/earnings' in text
    assert "网页摘要" in text


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "//example.com",
                                     "https://", "https://a:bad/x", "https://a\nb/x",
                                     "https://user:pass@example.com", "https://a\\b/x"])
def test_unsafe_or_invalid_sources_cannot_become_links(url):
    assert safe_source_url(url) is None
    sources = {}
    assert "citation" not in annotate_sources(article(url=url), sources)
    assert sources == {}


def test_missing_sources_stay_readable_and_titles_cannot_inject_markdown():
    sources = {}
    row = annotate_sources(article(title='<b>Title</b> "quote"', summary='a | b \\ " onclick="x'), sources)
    text = resolve_citations(row["citation"] + "[[cite:invented]]", sources)
    assert "[来源不可用]" in text
    assert "<b>" not in text and 'onclick="' not in text
    assert "&#124;" in text and "&#92;" in text and "&quot;" in text
    assert resolve_citations("旧报告，没有引用。", {}) == "旧报告，没有引用。"


def test_telegram_keeps_number_and_exact_url_without_tooltip_markup():
    from notifier.telegram import _md_to_telegram_html
    sources = {}
    row = annotate_sources(article(url="https://example.com/a_b_c_(d)?x=1&y=2"), sources)
    text = resolve_citations("**结论**" + row["citation"], sources)
    result = _md_to_telegram_html(text)
    assert '<a href="https://example.com/a_b_c_(d)?x=1&amp;y=2">[1]</a>' in result
    assert "<b>结论</b>" in result
    assert "收入增长" not in result


@pytest.mark.parametrize("forced", [False, True])
def test_graph_resolves_retrieved_sources_in_final_and_forced_answers(monkeypatch, forced):
    from agent import graph as module
    logged = []

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            results = [m for m in messages if isinstance(m, ToolMessage)]
            if not results:
                return AIMessage(content="", tool_calls=[{
                    "name": "web_search", "id": "search", "args": {"query": "财报"},
                }])
            payload = json.loads(results[-1].content)
            return AIMessage(content="增长" + payload["results"][0]["citation"])

    monkeypatch.setattr(module, "build_deepseek_llm", FakeLLM)
    monkeypatch.setattr(module.config, "AGENT_MAX_ROUNDS", 1 if forced else 3)
    monkeypatch.setattr(module, "execute_tool_calls", lambda *a: {"messages": [
        ToolMessage(name="web_search", tool_call_id="search",
                    content=json.dumps({"results": [article()]})),
    ]})
    monkeypatch.setattr(module, "_persist_tool_calls", lambda state, msgs: logged.extend(msgs))
    result = module.build_agent_graph().invoke({"messages": [HumanMessage(content="分析")],
                                               "session_id": 1, "extra_context": ""})
    assert '[\\[1\\]](' in result["messages"][-1].content
    assert "[[cite:" not in result["messages"][-1].content
    assert "citation" in json.loads(logged[0].content)["results"][0]


def test_news_context_preserves_source_and_citation():
    from agent.session import AgentSessionManager
    sources = {}
    rows = annotate_sources([article()], sources)
    text = AgentSessionManager("event").snapshot_news_for_context(rows)
    assert rows[0]["citation"] in text
    assert rows[0]["url"] in text
    assert rows[0]["summary"] in text


@pytest.mark.parametrize("uri", ["https://wallstreetcn.com/articles/123", "/articles/123", "123"])
def test_news_links_do_not_duplicate_article_prefix(uri):
    from adapters.news import WallStreetCNAdapter
    row = WallStreetCNAdapter._parse_items([{"title": "新闻", "uri": uri}])[0]
    assert row["url"] == "https://wallstreetcn.com/articles/123"


def test_citations_remain_self_contained_on_both_sides_of_chart():
    from app.components import kline_chart
    sources = {}
    row = annotate_sources(article(), sources)
    token = row["citation"]
    report = resolve_citations(f"前{token}\n```kline\n{{}}\n```\n后{token}", sources)
    rendered = []

    class UI:
        markdown = staticmethod(rendered.append)
        caption = staticmethod(lambda text: None)

    kline_chart.render_report(report, key_prefix="citations", ui=UI())
    assert len(rendered) == 2
    assert all('[\\[1\\]](' in text and "收入增长" in text for text in rendered)


def test_news_trigger_passes_source_metadata_and_saves_resolved_report(monkeypatch):
    from agent import core
    from agent.citations import CITATION_TOKEN
    saved = []

    class Session:
        session_id = 1
        snapshot_news_for_context = core.AgentSessionManager.snapshot_news_for_context
        start = lambda self: 1
        finish = lambda self, summary: saved.append(summary)

    def invoke(session, state):
        token = CITATION_TOKEN.search(state["extra_context"]).group()
        report = resolve_citations("结论" + token, state["citation_sources"])
        return {"messages": [AIMessage(content=report)]}

    monkeypatch.setattr(core, "AgentSessionManager", lambda **kwargs: Session())
    monkeypatch.setattr(core, "_invoke_agent", invoke)
    result = core.run_news_triggered_analysis([article()])
    assert result == saved[0]
    assert '[\\[1\\]](' in result and "收入增长" in result


def test_stream_done_and_saved_summary_use_resolved_answer(monkeypatch):
    from agent import core
    from langchain_core.messages import AIMessageChunk
    sources = {}
    row = annotate_sources(article(), sources)
    raw = "结论" + row["citation"]
    final = resolve_citations(raw, sources)
    saved = []

    class Session:
        session_id = 1
        start_or_resume = lambda self, sid: 1
        record_message = lambda *args: None
        finish = lambda self, summary: saved.append(summary)

    def stream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content=raw), {})
        yield "updates", {"agent": {"messages": [AIMessage(content=final)]}}

    monkeypatch.setattr(core, "AgentSessionManager", lambda **kwargs: Session())
    monkeypatch.setattr(core.agent_graph, "stream", stream)
    events = list(core.run_ad_hoc_query_stream("分析"))
    assert events[-1]["type"] == "done" and events[-1]["text"] == final
    assert final in saved[0] and "[[cite:" not in saved[0]
