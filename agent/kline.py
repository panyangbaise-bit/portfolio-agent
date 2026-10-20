"""Deterministic volume indicators; no provider calls or model-generated prices."""

import math


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def enrich_kline(rows: list[dict] | dict, market: str) -> list[dict] | dict:
    """Keep the list contract, normalize missing volume, add trailing indicators.

    MA windows include the current bar. ratio5 uses the *previous* five bars.
    Missing samples or insufficient history produce None, never fabricated zeroes.
    """
    if isinstance(rows, dict):
        if rows.get("error"):
            return rows
        raise ValueError("Expected a price series, not an unrecognized object")
    result = []
    volumes = []
    for source in sorted(rows, key=lambda row: row["date"]):
        row = dict(source)
        volume = finite_number(row.get("volume"))
        if volume is not None and volume < 0:
            volume = None
        row["volume"] = volume
        row.setdefault("series_kind", "price" if "price" in row else "ohlc")
        row.setdefault("volume_unit", "lot" if market.upper() == "CN" else "share")
        row.setdefault("volume_kind", "traded_volume")
        if row["series_kind"] == "nav":
            volume = None
            row["volume"] = None
            row["volume_unit"] = None
            row["volume_kind"] = "unavailable"
            row["analysis_limitations"] = (
                "净值无日内高低价和成交量；缩量、影线、日内反转条件均无法判断"
            )

        def average(values, window):
            if len(values) != window or any(v is None for v in values):
                return None
            return sum(values) / window

        previous_mean = average(volumes[-5:], 5)
        previous = volumes[-1] if volumes else None
        row["volume_ratio5"] = (
            round(volume / previous_mean, 4)
            if volume is not None and previous_mean is not None and previous_mean > 0
            else None
        )
        row["volume_change_pct"] = (
            round((volume / previous - 1) * 100, 2)
            if volume is not None and previous is not None and previous > 0
            else None
        )
        volumes.append(volume)
        for window in (5, 10, 20):
            value = average(volumes[-window:], window)
            row[f"volume_ma{window}"] = round(value, 4) if value is not None else None
        result.append(row)
    return result
