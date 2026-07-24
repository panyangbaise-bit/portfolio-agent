import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent


class Config:
    # Database
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'portfolio.db'}"

    # DeepSeek (OpenAI-compatible API) — deepseek-v4-pro + thinking mode by default
    # Docs: https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
    DEEPSEEK_API_KEY: str = os.environ["DEEPSEEK_API_KEY"]
    DEEPSEEK_BASE_URL: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    # Max output tokens (model allows up to 384K; 64K is a practical agent default).
    DEEPSEEK_MAX_TOKENS: int = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "65536"))
    # Thinking intensity: high | max (agent workloads use max).
    DEEPSEEK_REASONING_EFFORT: str = os.environ.get("DEEPSEEK_REASONING_EFFORT", "max")
    DEEPSEEK_THINKING: bool = os.environ.get("DEEPSEEK_THINKING", "true").lower() in (
        "1", "true", "yes", "on",
    )
    # Per-request HTTP timeout for chat/completions (seconds). Prevents indefinite hangs.
    DEEPSEEK_TIMEOUT: float = float(os.environ.get("DEEPSEEK_TIMEOUT", "300"))

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Scheduler / agent run limits
    # Overall LangGraph invoke budget (multi-round tools + LLM). Must be >= DEEPSEEK_TIMEOUT.
    AGENT_RUN_TIMEOUT: float = float(os.environ.get("AGENT_RUN_TIMEOUT", "1200"))
    # Default news poll: 08:00–22:00 Asia/Shanghai every 2 hours (editable on Jobs page).
    # 5-field crontab: minute hour day month day_of_week
    DEFAULT_NEWS_CRONTAB: str = os.environ.get("NEWS_CRONTAB", "0 8-22/2 * * *")

    # Display / logging timezone (DB timestamps stay UTC; UI converts for display).
    # Default Beijing time. Override with e.g. APP_TIMEZONE=America/New_York
    APP_TIMEZONE: str = os.environ.get("APP_TIMEZONE", "Asia/Shanghai")

    # Public access gate (password never exposed to clients except typed form input)
    AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "false").lower() in (
        "1", "true", "yes", "on",
    )
    AUTH_PASSWORD: str = os.environ.get("AUTH_PASSWORD", "")
    AUTH_MAX_FAILURES: int = int(os.environ.get("AUTH_MAX_FAILURES", "3"))

    # News API
    WALLSTREETCN_BASE_URL: str = "https://api-one-wscn.awtmt.com/apiv1"

    # Markets that require trading-day checks (crypto is 24/7)
    TRADING_MARKETS: dict = {
        "US": {"timezone": "America/New_York", "close_hour": 16, "close_minute": 0},
        "CN": {"timezone": "Asia/Shanghai", "close_hour": 15, "close_minute": 0},
        "HK": {"timezone": "Asia/Hong_Kong", "close_hour": 16, "close_minute": 0},
    }


config = Config()
