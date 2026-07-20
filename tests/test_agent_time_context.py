"""Agent wall-clock context for system prompts."""

from app.timeutil import format_now_for_agent


def test_format_now_for_agent_includes_heading_and_timezone(monkeypatch):
    monkeypatch.setattr("app.timeutil.config.APP_TIMEZONE", "Asia/Shanghai")

    block = format_now_for_agent()

    assert block.startswith("## 当前时间\n")
    assert "(Asia/Shanghai)" in block
    # YYYY-MM-DD HH:MM
    stamp = block.split("\n", 1)[1].split(" ", 1)[0]
    assert len(stamp) == 10
    assert stamp[4] == "-" and stamp[7] == "-"
