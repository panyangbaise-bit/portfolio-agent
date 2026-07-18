import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent


class Config:
    # Database
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'portfolio.db'}"

    # DeepSeek (OpenAI-compatible API)
    DEEPSEEK_API_KEY: str = os.environ["DEEPSEEK_API_KEY"]
    DEEPSEEK_BASE_URL: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Scheduler
    NEWS_POLL_INTERVAL_MINUTES: int = 60

    # News API
    WALLSTREETCN_BASE_URL: str = "https://api-one-wscn.awtmt.com/apiv1"

    # Markets that require trading-day checks (crypto is 24/7)
    TRADING_MARKETS: dict = {
        "US": {"timezone": "America/New_York", "close_hour": 16, "close_minute": 0},
        "CN": {"timezone": "Asia/Shanghai", "close_hour": 15, "close_minute": 0},
        "HK": {"timezone": "Asia/Hong_Kong", "close_hour": 16, "close_minute": 0},
    }


config = Config()
