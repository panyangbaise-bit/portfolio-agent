#!/bin/bash
# Launch script for Portfolio Agent

set -e

cd "$(dirname "$0")"

echo "=================================="
echo "  📊 Portfolio Agent"
echo "=================================="

if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copy .env.example to .env and fill in your keys."
    echo ""
    echo "Required: DEEPSEEK_API_KEY"
    echo "Optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    exit 1
fi

echo "🚀 Starting Streamlit..."
python3 -m streamlit run app/main.py --server.port 8501
