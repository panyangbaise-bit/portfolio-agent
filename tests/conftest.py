"""Keep the default suite isolated from local credentials and the live ledger."""

import os
import tempfile
from pathlib import Path

# These must be set before application modules import config during collection.
# Provider-specific tests replace transports with deterministic fixtures.
_test_data = tempfile.TemporaryDirectory(prefix="portfolio-agent-tests-")
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_test_data.name) / 'test.db'}"
os.environ["DEEPSEEK_API_KEY"] = "test-only-not-a-real-key"
for key in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "MEMORY_EMBEDDING_API_KEY",
    "DASHSCOPE_API_KEY",
    "MEMORY_QDRANT_API_KEY",
    "A2A_TOKEN",
    "ACTIONS_TOKEN",
):
    os.environ[key] = ""
for key in (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "MEMORY_VECTOR_ENABLED",
    "A2A_ENABLED",
    "ACTIONS_ENABLED",
):
    os.environ[key] = "false"
