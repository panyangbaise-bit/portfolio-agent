"""Render saved report figures without fetching or executing model-supplied code."""

import json
import logging
import re
from html import escape

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app.i18n import t, translate
from db.models import AnalysisChart
from db.repository import get_session

logger = logging.getLogger(__name__)
CHART_BLOCK = re.compile(r"^```kline\s*\n(.*?)\n```[ \t]*$", re.MULTILINE | re.DOTALL)


def build_kline_figure(payload: dict, locale: str = "zh") -> go.Figure:
    locale = "zh" if locale in ("zh", "cn") else "en"

    def label(key, **kw):
        return translate(locale, "chart." + key, **kw)

    bars = payload["bars"]
    dates = [bar["date"] for bar in bars]
    closes = [bar.get("close", bar.get("price")) for bar in bars]
    kind = bars[0].get("series_kind", "ohlc")
    has_volume = any(bar.get("volume") is not None for bar in bars)
    fig = make_subplots(
        rows=2 if has_volume else 1,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28] if has_volume else [1],
    )
    red, green = "#f87171", "#34d399"
    up, down = (red, green) if locale == "zh" else (green, red)
    if kind == "ohlc":
        fig.add_trace(
            go.Candlestick(
                x=dates,
                open=[b["open"] for b in bars],
                high=[b["high"] for b in bars],
                low=[b["low"] for b in bars],
                close=closes,
                name=label("ohlc"),
                increasing_line_color=up,
                decreasing_line_color=down,
            ),
            row=1,
            col=1,
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=closes,
                mode="lines",
                name=label("nav" if kind == "nav" else "price"),
                line={"color": "#60a5fa", "width": 2},
            ),
            row=1,
            col=1,
        )
    if has_volume:
        colors = [
            up if close >= bar.get("open", closes[max(0, i - 1)]) else down
            for i, (bar, close) in enumerate(zip(bars, closes))
        ]
        volume_label = (
            label("turnover")
            if bars[0].get("volume_kind") == "rolling_24h_turnover"
            else label("volume")
        )
        unit = label(bars[0].get("volume_unit") or "unknown_unit")
        fig.add_trace(
            go.Bar(
                x=dates,
                y=[b.get("volume") for b in bars],
                name=f"{volume_label} ({unit})",
                marker_color=colors,
                opacity=0.6,
            ),
            row=2,
            col=1,
        )
        for window, color in ((5, "#fbbf24"), (10, "#60a5fa"), (20, "#c084fc")):
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=[b.get(f"volume_ma{window}") for b in bars],
                    mode="lines",
                    name=f"VMA{window}",
                    line={"color": color, "width": 1.5},
                    connectgaps=False,
                ),
                row=2,
                col=1,
            )
        fig.update_yaxes(title_text=unit, rangemode="tozero", row=2, col=1)
    for i, note in enumerate(payload.get("annotations", [])):
        # Plotly text supports HTML; escape all model-generated labels.
        fig.add_annotation(
            x=note["date"],
            y=note["price"],
            text=escape(note["text"]),
            showarrow=True,
            arrowhead=2,
            ax=0,
            ay=-45 - (i % 3) * 28,
            bgcolor="#1e293b",
            bordercolor="#64748b",
            font={"color": "#f8fafc", "size": 11},
            row=1,
            col=1,
        )
    for line in payload.get("lines", []):
        color = {"support": "#34d399", "resistance": "#fbbf24", "trend": "#60a5fa"}[line["kind"]]
        fig.add_shape(
            type="line",
            x0=line["start_date"],
            x1=line["end_date"],
            y0=line["start_price"],
            y1=line["end_price"],
            line={"color": color, "width": 2, "dash": "dash"},
            row=1,
            col=1,
        )
        fig.add_annotation(
            x=line["end_date"],
            y=line["end_price"],
            text=escape(line["text"]),
            showarrow=False,
            yshift=12,
            xanchor="right",
            font={"color": color, "size": 11},
            row=1,
            col=1,
        )
    currency = {"US": "USD", "HK": "HKD", "CN": "CNY", "CRYPTO": "USD"}.get(payload["market"], "")
    fig.update_yaxes(title_text=currency, row=1, col=1)
    fig.update_yaxes(color="#cbd5e1", gridcolor="#263449", zerolinecolor="#334155")
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=dates,
        rangeslider_visible=False,
        nticks=8,
        showgrid=False,
        color="#cbd5e1",
    )
    fig.update_layout(
        title={"text": escape(payload["title"]), "font": {"size": 18, "color": "#f8fafc"}},
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font={"color": "#cbd5e1"},
        height=620 if has_volume else 450,
        margin={"l": 55, "r": 35, "t": 75, "b": 40},
        legend={"orientation": "h", "y": 1.06, "font": {"size": 11, "color": "#cbd5e1"}},
        hovermode="x unified",
        dragmode="zoom",
    )
    return fig


def load_chart(chart_id: str):
    with get_session() as db:
        chart = db.get(AnalysisChart, chart_id)
        return chart.payload if chart else None


def render_report(content: str, *, key_prefix: str, ui=None):
    """Mix ordinary Markdown with bounded, validated chart references."""
    ui = st if ui is None else ui
    offset = 0
    for index, match in enumerate(CHART_BLOCK.finditer(content)):
        before = content[offset : match.start()]
        if before.strip():
            ui.markdown(before)
        try:
            if index >= 12 or len(match.group(1)) > 200:
                raise ValueError("Too many or oversized chart references")
            ref = json.loads(match.group(1))
            chart_id = ref["chart_id"]
            if not isinstance(chart_id, str) or not re.fullmatch(r"[0-9a-f]{32}", chart_id):
                raise ValueError("Invalid chart id")
            payload = load_chart(chart_id)
            if not payload or payload.get("version") != 1:
                raise ValueError("Chart unavailable")
            locale = st.session_state.get("locale", "en")
            ui.plotly_chart(
                build_kline_figure(payload, locale),
                use_container_width=True,
                theme=None,
                key=f"{key_prefix}_chart_{index}_{chart_id}",
                config={
                    "displaylogo": False,
                    "toImageButtonOptions": {
                        "format": "png",
                        "filename": f"kline-{chart_id}",
                        "scale": 2,
                    },
                },
            )
            bars = payload["bars"]
            ui.caption(
                t(
                    "chart.snapshot",
                    ticker=payload["ticker"],
                    market=payload["market"],
                    period=payload["period"],
                    start=bars[0]["date"],
                    end=bars[-1]["date"],
                )
            )
            ui.caption(t("chart.note"))
            if bars[0].get("series_kind") == "nav":
                ui.caption(t("chart.nav_note"))
            elif bars[0].get("volume_kind") == "rolling_24h_turnover":
                ui.caption(t("chart.crypto_note"))
            elif not any(b.get("volume") is not None for b in bars):
                ui.caption(t("chart.no_volume"))
        except Exception:
            # A missing artifact/dependency must not hide the rest of a report.
            logger.warning("Unable to render report chart", exc_info=True)
            ui.caption(t("chart.unavailable"))
        offset = match.end()
    if content[offset:].strip():
        ui.markdown(content[offset:])
