"""Telegram Bot notification sender."""

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from config import config
from app.timeutil import format_display_time
from db.repository import apply_recommendation_action, get_session

logger = logging.getLogger(__name__)

# Telegram imposes a 4096-character limit per message.
MAX_MESSAGE_LENGTH = 4000

# Process-lifetime guard — Streamlit refreshes reset session_state but not this.
_welcome_sent = False
_welcome_lock = threading.Lock()
_callback_poller = None
_callback_poller_lock = threading.Lock()


def _is_configured() -> bool:
    """Check if Telegram is configured (token + chat_id are set)."""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _md_to_telegram_html(text: str) -> str:
    """Convert common Markdown patterns to Telegram-compatible HTML.

    Telegram's HTML parse mode only supports a limited set of tags:
    <b>, <i>, <u>, <s>, <tg-spoiler>, <a>, <code>, <pre>.
    Tables, headings, and horizontal rules have no HTML equivalent so we
    reformat them into readable alternatives.
    """
    # --- 1. Code blocks (``` ... ```) — convert to <pre> ---
    text = re.sub(r"```(\w*)\n?(.*?)```", r"<pre>\2</pre>", text, flags=re.DOTALL)

    # --- 2. Inline code (`...`) ---
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)

    # --- 3. Horizontal rules ---
    text = re.sub(r"^[-*_]{3,}$", "▬▬▬▬▬▬▬▬", text, flags=re.MULTILINE)

    # --- 4. Markdown tables → compact text representation ---
    # Match a markdown table block (header row + separator + body rows).
    # Use greedy (.+) inside outer |...| so we capture all columns.
    table_re = re.compile(
        r"^\|(.+)\|\n\|[-:|\s]+?\|\n((?:\|.+\|[\n\r]?)+)", re.MULTILINE
    )
    def _table_replacer(m: re.Match) -> str:
        header = m.group(1)
        body = m.group(2)
        headers = [h.strip() for h in header.split("|")]
        rows = []
        for line in body.strip().split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == len(headers) and cells:
                row_parts = [f"<b>{h}:</b> {v}" for h, v in zip(headers, cells)]
                rows.append(" | ".join(row_parts))
        return "\n".join(rows) if rows else m.group(0)

    text = table_re.sub(_table_replacer, text)

    # --- 5. Headings (### Title) → bold ---
    text = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # --- 6. Bold (**text** or __text__) ---
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # --- 7. Italic (*text* or _text_) — but not inside URLs ---
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)([^_\n]+?)_(?!_)", r"<i>\1</i>", text)

    # --- 8. Unordered list items ---
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # --- 9. Inline links [text](url) ---
    text = re.sub(r"\[([^\]]+?)\]\(([^)]+?)\)", r'<a href="\2">\1</a>', text)

    # --- 10. Strip unsupported-but-harmless markdown cruft ---
    # Remove stray | that aren't in HTML tags (leftover from table conversion)
    # Actually, keep them — they may be intentional separators.

    return text


def _escape_unsafe_html(text: str) -> str:
    """Escape <, >, & outside of valid Telegram HTML tags.

    After _md_to_telegram_html() converts markdown to <b>, <i>, etc.,
    the output may still contain raw < characters (like "<2%") that
    Telegram's parser misinterprets as HTML tags. This function escapes
    those dangerous characters while leaving valid tags untouched.
    """
    valid = r"b|i|u|s|tg-spoiler|a|code|pre"
    tag_re = re.compile(r"<(/?)(?:" + valid + r")(?:\s[^>]*)?>", re.IGNORECASE)

    result = []
    last_end = 0
    for match in tag_re.finditer(text):
        before = text[last_end:match.start()]
        result.append(before.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        result.append(match.group())
        last_end = match.end()
    remaining = text[last_end:]
    result.append(remaining.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    return "".join(result)


def _send_message(text: str, reply_markup: Optional[dict] = None):
    """Send a single Telegram message, falling back to plain-text on HTML parse error."""
    import requests

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        resp_data = resp.json()
        # If HTML parse error, retry as plain text so the message still gets delivered.
        if resp.status_code == 400 and "can't parse entities" in resp_data.get("description", ""):
            logger.warning(
                "Telegram HTML parse failed (unbalanced tags), retrying as plain text. "
                f"Error: {resp.text}"
            )
            payload["parse_mode"] = ""
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Telegram plain-text retry also failed: {resp.status_code} {resp.text}")
                return
        else:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
            return

    logger.info("Telegram message sent OK.")


def notify(message: str):
    """Send a Telegram notification, splitting long messages if needed."""
    if not _is_configured():
        logger.debug("Telegram not configured, skipping notification.")
        return

    html = _md_to_telegram_html(message)
    html = _escape_unsafe_html(html)

    try:
        if len(html) <= MAX_MESSAGE_LENGTH:
            _send_message(html)
            logger.info("Telegram notification sent.")
        else:
            # Split at paragraph boundaries.
            parts = html.split("\n\n")
            chunk = ""
            for part in parts:
                candidate = chunk + ("\n\n" if chunk else "") + part
                if len(candidate) > MAX_MESSAGE_LENGTH and chunk:
                    _send_message(chunk)
                    chunk = part
                else:
                    chunk = candidate
            if chunk:
                _send_message(chunk)
            logger.info(f"Telegram notification sent in {len(parts)} parts.")
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")


def send_welcome():
    """Send a one-time process startup notification (not on page refresh)."""
    global _welcome_sent
    with _welcome_lock:
        if _welcome_sent:
            logger.info("Skipping Telegram welcome — already sent this process.")
            return
        _welcome_sent = True

    now = format_display_time(datetime.now(timezone.utc))
    notify(f"🤖 <b>Portfolio Agent 已启动</b>\n<code>{now}</code>")


def send_urgent_recommendation(ticker: str, action: str, reasoning: str, confidence: float):
    """Send a high-urgency recommendation as a formatted Telegram message."""
    action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
    emoji = action_emoji.get(action, "ℹ️")

    msg = (
        f"{emoji} <b>建议操作</b>\n\n"
        f"<b>标的：</b>{ticker}\n"
        f"<b>建议：</b>{action}\n"
        f"<b>置信度：</b>{confidence:.0%}\n\n"
        f"<b>理由：</b>\n{reasoning}"
    )
    notify(msg)


def send_recommendation(recommendation):
    """Send a pending recommendation with Telegram Accept/Dismiss buttons."""
    if not _is_configured():
        logger.debug("Telegram not configured, skipping recommendation.")
        return

    action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
    emoji = action_emoji.get(recommendation.action, "ℹ️")
    message = (
        f"{emoji} <b>投资建议</b>\n\n"
        f"<b>标的：</b>{recommendation.ticker}\n"
        f"<b>操作：</b>{recommendation.action}\n"
        f"<b>紧急度：</b>{recommendation.urgency}\n"
        f"<b>置信度：</b>{recommendation.confidence:.0%}\n\n"
        f"<b>理由：</b>\n{recommendation.reasoning}"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Accept", "callback_data": f"rec:{recommendation.id}:accept"},
            {"text": "❌ Dismiss", "callback_data": f"rec:{recommendation.id}:dismiss"},
        ]],
    }
    _send_message(
        _escape_unsafe_html(_md_to_telegram_html(message)),
        reply_markup=reply_markup,
    )


class TelegramCallbackPoller:
    """Long-poll Telegram callback queries on a daemon thread."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self._offset = None

    def start(self):
        if not _is_configured() or self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="telegram-callback-poller", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _answer_callback(self, callback_id: str, text: str, show_alert: bool = False):
        import requests

        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={
                "callback_query_id": callback_id,
                "text": text,
                "show_alert": show_alert,
            },
            timeout=10,
        )

    def process_update(self, update: dict):
        callback = update.get("callback_query") or {}
        callback_id = callback.get("id")
        if not callback_id:
            return

        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
            self._answer_callback(callback_id, "Unauthorized callback.", show_alert=True)
            return

        match = re.fullmatch(r"rec:(\d+):(accept|dismiss)", callback.get("data") or "")
        if not match:
            self._answer_callback(callback_id, "Invalid recommendation action.", show_alert=True)
            return

        recommendation_id = int(match.group(1))
        action = match.group(2)
        session = get_session()
        try:
            result = apply_recommendation_action(session, recommendation_id, action)
        finally:
            session.close()

        if result["status"] == "applied":
            text = "Recommendation accepted." if action == "accept" else "Recommendation dismissed."
            self._answer_callback(callback_id, text)
        elif result["status"] == "already_handled":
            self._answer_callback(callback_id, "Recommendation was already handled.")
        else:
            self._answer_callback(callback_id, "Recommendation is no longer available.", show_alert=True)

    def _run(self):
        import requests

        delay = 1
        max_delay = getattr(config, "TELEGRAM_POLL_MAX_BACKOFF", 60)
        poll_timeout = getattr(config, "TELEGRAM_POLL_TIMEOUT", 30)
        while not self._stop_event.is_set():
            try:
                params = {"timeout": poll_timeout}
                if self._offset is not None:
                    params["offset"] = self._offset
                response = requests.get(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
                    params=params,
                    timeout=poll_timeout + 10,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise ValueError("Telegram getUpdates returned not ok")
                delay = 1
                for update in payload.get("result", []):
                    self._offset = update["update_id"] + 1
                    self.process_update(update)
            except Exception as exc:
                logger.warning("Telegram callback poll failed: %s", exc)
                self._stop_event.wait(delay)
                delay = min(delay * 2, max_delay)


def start_callback_poller():
    """Start one process-wide callback poller when Telegram is configured."""
    global _callback_poller
    with _callback_poller_lock:
        if _callback_poller is None:
            _callback_poller = TelegramCallbackPoller()
        _callback_poller.start()
    return _callback_poller


def stop_callback_poller():
    """Request shutdown of the process-wide callback poller."""
    if _callback_poller is not None:
        _callback_poller.stop()


def discover_chat_id() -> Optional[str]:
    """Try to discover the chat ID from recent Telegram updates.

    Returns the chat_id of the most recent message sent to the bot,
    or None if no messages are found.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        return None

    try:
        import requests

        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"getUpdates failed: {resp.status_code} {resp.text}")
            return None

        data = resp.json()
        if not data.get("ok"):
            logger.error(f"getUpdates returned not ok: {data}")
            return None

        updates = data.get("result", [])
        if not updates:
            logger.info("No Telegram updates found — no one has messaged the bot yet.")
            return None

        # Return the chat_id from the most recent message
        latest = updates[-1]
        chat_id = None
        if "message" in latest:
            chat_id = latest["message"]["chat"]["id"]
        elif "channel_post" in latest:
            chat_id = latest["channel_post"]["chat"]["id"]

        if chat_id:
            logger.info(f"Discovered chat ID: {chat_id}")
        return str(chat_id) if chat_id else None

    except Exception as e:
        logger.error(f"discover_chat_id error: {e}")
        return None


def get_bot_username() -> Optional[str]:
    """Get the bot's username via getMe API."""
    if not config.TELEGRAM_BOT_TOKEN:
        return None

    try:
        import requests

        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data["result"]["username"]
    except Exception as e:
        logger.error(f"getMe error: {e}")
    return None


def is_configured() -> bool:
    """Public accessor for the configured check."""
    return _is_configured()
