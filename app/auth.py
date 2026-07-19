"""Optional password gate + IP blacklist for public deployments.

Password lives only in server-side config/env (never sent to the client except
as a typed form value). Failed attempts are counted per client IP; after
AUTH_MAX_FAILURES the IP is persisted to a local blacklist file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

from app.i18n import t
from config import PROJECT_ROOT, config

logger = logging.getLogger(__name__)

_BLACKLIST_PATH = PROJECT_ROOT / "data" / "ip_blacklist.json"
_LOCK = threading.Lock()
# ip -> consecutive failure count (process memory; blacklist file is durable)
_FAILURES = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_blacklist() -> dict:
    if not _BLACKLIST_PATH.is_file():
        return {}
    try:
        data = json.loads(_BLACKLIST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read IP blacklist: %s", e)
        return {}


def _save_blacklist(data: dict) -> None:
    _BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _BLACKLIST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_BLACKLIST_PATH)


def get_client_ip() -> str:
    """Best-effort client IP for auth throttling (proxy-aware)."""
    headers = {}
    try:
        headers = st.context.headers or {}
    except Exception:
        headers = {}

    def _header(name: str) -> Optional[str]:
        # Streamlit headers behave like a case-insensitive mapping.
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if not value:
            return None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return str(value).strip() if value else None

    forwarded = _header("X-Forwarded-For") or _header("x-forwarded-for")
    if forwarded:
        # Left-most is the original client when set by a trusted reverse proxy.
        return forwarded.split(",")[0].strip() or "unknown"

    real_ip = _header("X-Real-IP") or _header("x-real-ip")
    if real_ip:
        return real_ip

    try:
        ip = st.context.ip_address
        if ip:
            return str(ip)
    except Exception:
        pass

    # Localhost / missing IP — still track so auth logic stays consistent.
    return "127.0.0.1"


def is_ip_blacklisted(ip: str) -> bool:
    with _LOCK:
        return ip in _load_blacklist()


def blacklist_ip(ip: str, reason: str = "auth_failures") -> None:
    with _LOCK:
        data = _load_blacklist()
        data[ip] = {
            "reason": reason,
            "blacklisted_at": _utcnow_iso(),
        }
        _save_blacklist(data)
        _FAILURES.pop(ip, None)
    logger.warning("Blacklisted IP %s (%s)", ip, reason)


def record_auth_failure(ip: str) -> int:
    """Increment failure count; blacklist at threshold. Returns new count."""
    max_failures = max(1, int(config.AUTH_MAX_FAILURES))
    with _LOCK:
        count = int(_FAILURES.get(ip, 0)) + 1
        _FAILURES[ip] = count
        should_ban = count >= max_failures
    if should_ban:
        blacklist_ip(ip, reason="auth_failures:%d" % count)
    return count


def clear_auth_failures(ip: str) -> None:
    with _LOCK:
        _FAILURES.pop(ip, None)


def auth_enabled() -> bool:
    return bool(config.AUTH_ENABLED)


def password_configured() -> bool:
    return bool(config.AUTH_PASSWORD)


def verify_password(candidate: str) -> bool:
    expected = config.AUTH_PASSWORD or ""
    if not expected:
        return False
    # Hash first so unequal lengths never raise in compare_digest.
    left = hashlib.sha256((candidate or "").encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(left, right)


def _render_blocked(ip: str) -> None:
    st.title(t("auth.blocked.title"))
    st.error(t("auth.blocked.body", ip=ip))
    st.caption(t("auth.blocked.hint"))


def _render_login(ip: str) -> None:
    st.title(t("auth.login.title"))
    st.caption(t("auth.login.caption"))

    if not password_configured():
        st.error(t("auth.misconfigured"))
        return

    with st.form("auth_login_form", clear_on_submit=True):
        password = st.text_input(
            t("auth.login.password"),
            type="password",
            autocomplete="current-password",
        )
        submitted = st.form_submit_button(t("auth.login.submit"), type="primary")

    if not submitted:
        return

    if verify_password(password or ""):
        clear_auth_failures(ip)
        st.session_state["auth_ok"] = True
        st.session_state["auth_ip"] = ip
        st.rerun()

    failures = record_auth_failure(ip)
    remaining = max(0, int(config.AUTH_MAX_FAILURES) - failures)
    if is_ip_blacklisted(ip):
        st.rerun()
    st.error(t("auth.login.failed", remaining=remaining))


def require_auth() -> None:
    """Gate the Streamlit app when AUTH_ENABLED is on. Calls st.stop() if blocked."""
    if not auth_enabled():
        return

    ip = get_client_ip()

    if is_ip_blacklisted(ip):
        _render_blocked(ip)
        st.stop()

    if st.session_state.get("auth_ok") and st.session_state.get("auth_ip") == ip:
        return

    # Session marked ok but IP changed — force re-auth.
    if st.session_state.get("auth_ok"):
        st.session_state.pop("auth_ok", None)

    _render_login(ip)
    st.stop()
