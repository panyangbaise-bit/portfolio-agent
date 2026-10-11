"""Human-readable descriptions for the 5-field crontabs this app schedules."""

from typing import Optional


def describe_cron(expr: str, locale: str = "en", timezone: str = "") -> str:
    """Describe a 5-field crontab in English or Chinese.

    Unsupported patterns fall back to the raw expression. The timezone, when
    given, is always appended so the clock is unambiguous.
    """
    text = _describe_fields(expr, locale)
    if not text:
        text = (expr or "").strip() or "—"
    if timezone:
        if locale == "zh":
            return f"{text}（{timezone}）"
        return f"{text} ({timezone})"
    return text


def _describe_fields(expr: str, locale: str) -> Optional[str]:
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        return None
    minute, hour, day, month, dow = (_parse_field(part) for part in parts)
    if any(field is None for field in (minute, hour, day, month, dow)):
        return None
    if month["kind"] != "any" or dow["kind"] != "any":
        return None
    if minute["kind"] != "value":
        return None

    minute_value = minute["value"]
    if not 0 <= minute_value <= 59:
        return None

    if day["kind"] == "any" and hour["kind"] == "value":
        if not 0 <= hour["value"] <= 23:
            return None
        clock = _clock(hour["value"], minute_value)
        if locale == "zh":
            return f"每天 {clock}"
        return f"Every day at {clock}"

    if day["kind"] == "any" and hour["kind"] == "range":
        return _describe_hour_range(hour, minute_value, locale)

    if day["kind"] == "any" and hour["kind"] == "step" and hour["start"] is None:
        return _describe_hour_step(hour["step"], minute_value, locale)

    if day["kind"] == "value" and hour["kind"] == "value":
        if not 1 <= day["value"] <= 31 or not 0 <= hour["value"] <= 23:
            return None
        clock = _clock(hour["value"], minute_value)
        if locale == "zh":
            return f"每月 {day['value']} 日 {clock}"
        return f"Every month on the {_ordinal(day['value'])} at {clock}"

    return None


def _describe_hour_range(hour: dict, minute_value: int, locale: str) -> Optional[str]:
    start, end, step = hour["start"], hour["end"], hour["step"]
    if not 0 <= start <= 23 or not 0 <= end <= 23 or start > end or step <= 0:
        return None
    start_clock = _clock(start, minute_value)
    end_clock = _clock(end, minute_value)
    if locale == "zh":
        if minute_value == 0 and step == 1:
            return f"每天 {start_clock}–{end_clock} 每小时整点"
        if minute_value == 0:
            return f"每天 {start_clock}–{end_clock} 每 {step} 小时整点"
        if step == 1:
            return f"每天 {start_clock}–{end_clock} 每小时"
        return f"每天 {start_clock}–{end_clock} 每 {step} 小时"
    if minute_value == 0 and step == 1:
        return f"Every day from {start_clock}–{end_clock}, every hour on the hour"
    if minute_value == 0:
        return f"Every day from {start_clock}–{end_clock}, every {step} hours on the hour"
    unit = "hour" if step == 1 else "hours"
    return f"Every day from {start_clock}–{end_clock}, every {step} {unit}"


def _describe_hour_step(step: int, minute_value: int, locale: str) -> Optional[str]:
    if step <= 0:
        return None
    if locale == "zh":
        if minute_value == 0 and step == 1:
            return "每小时整点"
        if minute_value == 0:
            return f"每 {step} 小时整点"
        if step == 1:
            return f"每小时的第 {minute_value} 分"
        return f"每 {step} 小时的第 {minute_value} 分"
    if minute_value == 0 and step == 1:
        return "Every hour on the hour"
    if minute_value == 0:
        return f"Every {step} hours on the hour"
    if step == 1:
        return f"Every hour at minute {minute_value}"
    return f"Every {step} hours at minute {minute_value}"


def _parse_field(token: str) -> Optional[dict]:
    token = token.strip()
    if not token or "," in token:
        return None
    step = None
    base = token
    if "/" in token:
        base, step_text = token.split("/", 1)
        if not step_text.isdigit() or int(step_text) <= 0:
            return None
        step = int(step_text)
    if base == "*":
        if step is None:
            return {"kind": "any"}
        return {"kind": "step", "start": None, "end": None, "step": step}
    if "-" in base:
        start_text, end_text = base.split("-", 1)
        if not (start_text.isdigit() and end_text.isdigit()):
            return None
        return {
            "kind": "range",
            "start": int(start_text),
            "end": int(end_text),
            "step": step or 1,
        }
    if base.isdigit() and step is None:
        return {"kind": "value", "value": int(base)}
    return None


def _clock(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"
