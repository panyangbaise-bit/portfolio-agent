"""Google OIDC login and server-side authorization for the private dashboard.

Streamlit/Authlib validates the authorization response (signature, audience,
state and nonce). Only its authenticated identity is trusted here, never
query parameters, proxy headers, or the old password session flag.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from app.i18n import t
from config import config

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def allowed_emails() -> set[str]:
    return {
        email.strip().lower() for email in config.AUTH_ALLOWED_EMAILS.split(",") if email.strip()
    }


def google_auth_configured() -> bool:
    """Missing or invalid configuration must block access, including old cookies."""
    try:
        auth = st.secrets["auth"]
        google = auth["google"]
        if not isinstance(auth, Mapping) or not isinstance(google, Mapping):
            return False
        if not all(
            isinstance(google.get(key), str) and google[key].strip()
            for key in ("client_id", "client_secret")
        ):
            return False
        if google.get("server_metadata_url") != GOOGLE_METADATA_URL:
            return False
        secret = auth.get("cookie_secret", "")
        if not isinstance(secret, str) or len(secret) < 32:
            return False
        url = urlsplit(auth.get("redirect_uri", ""))
        secure_origin = url.scheme == "https" or (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        return bool(
            secure_origin
            and url.hostname
            and not url.username
            and not url.password
            and url.path == "/oauth2callback"
            and not url.query
            and not url.fragment
        )
    except (StreamlitSecretNotFoundError, KeyError, TypeError, ValueError, AttributeError):
        return False


def is_authorized_user(user: Mapping) -> bool:
    """Recheck the allowlist on every rerun; never cache authorization in session state."""
    email = user.get("email")
    subject = user.get("sub")
    return (
        user.get("is_logged_in") is True
        and user.get("iss") in GOOGLE_ISSUERS
        and isinstance(subject, str)
        and bool(subject.strip())
        and user.get("email_verified") is True
        and isinstance(email, str)
        and email.strip().lower() in allowed_emails()
        # Google is authoritative for Gmail and verified Workspace addresses.
        and (email.lower().endswith("@gmail.com") or bool(user.get("hd")))
    )


def require_auth() -> None:
    """Stop before loading a private page unless the Google identity is allowed."""
    if not config.AUTH_ENABLED:
        return  # Explicit local-development opt-out only; enabled by default.

    if not allowed_emails() or not google_auth_configured():
        st.title(t("auth.login.title"))
        st.error(t("auth.misconfigured"))
        st.stop()

    if not st.user.is_logged_in:
        st.title(t("auth.login.title"))
        st.caption(t("auth.login.caption"))
        if st.button(t("auth.login.google"), type="primary", key="google_login"):
            st.login("google")
        st.stop()

    if not is_authorized_user(st.user):
        st.title(t("auth.blocked.title"))
        st.error(t("auth.blocked.body"))
        if st.button(t("auth.switch_account"), key="google_switch_account"):
            st.logout()
        st.stop()


def render_account_menu() -> None:
    """Called only after require_auth succeeds."""
    if config.AUTH_ENABLED:
        st.sidebar.caption(st.user.get("email", ""))
        if st.sidebar.button(t("auth.logout"), key="google_logout"):
            st.logout()
            st.stop()
