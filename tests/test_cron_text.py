"""Human-readable crontab descriptions for the Jobs page."""

from scheduler.cron import FIXED_JOB_CRONS, job_cron
from scheduler.cron_text import describe_cron


def test_default_news_crontab_zh():
    text = describe_cron("0 8-22/2 * * *", "zh", "Asia/Shanghai")
    assert text == "每天 08:00–22:00 每 2 小时整点（Asia/Shanghai）"


def test_default_news_crontab_en():
    text = describe_cron("0 8-22/2 * * *", "en", "Asia/Shanghai")
    assert text == (
        "Every day from 08:00–22:00, every 2 hours on the hour (Asia/Shanghai)"
    )


def test_fixed_job_crons_translate():
    expected = {
        "us_after_market": "每天 07:30（Asia/Shanghai）",
        "cn_after_market": "每天 15:30（Asia/Shanghai）",
        "hk_after_market": "每天 16:30（Asia/Hong_Kong）",
        "crypto_daily": "每天 21:00（Asia/Shanghai）",
        "monthly_trade_review": "每月 1 日 21:00（Asia/Shanghai）",
    }
    for job_id, sentence in expected.items():
        expr, tz = job_cron(job_id)
        assert (expr, tz) == FIXED_JOB_CRONS[job_id]
        assert describe_cron(expr, "zh", tz) == sentence


def test_monthly_ordinal_en():
    assert describe_cron("0 21 1 * *", "en", "Asia/Shanghai") == (
        "Every month on the 1st at 21:00 (Asia/Shanghai)"
    )


def test_unsupported_expr_falls_back_to_raw():
    assert describe_cron("0 8-22/2 * * 1", "zh", "Asia/Shanghai") == (
        "0 8-22/2 * * 1（Asia/Shanghai）"
    )
