"""Google identity authorization and dashboard gate regression tests."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.runtime.secrets import AttrDict
from streamlit.runtime.scriptrunner import StopException
from streamlit.testing.v1 import AppTest

import app.auth as auth


OWNER = "owner@gmail.com"
SETTINGS = {"auth": {
    "redirect_uri": "https://portfolio.example.com/oauth2callback",
    "cookie_secret": "x" * 64,
    "google": {
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "server_metadata_url": auth.GOOGLE_METADATA_URL,
    },
}}
IDENTITY = {
    "is_logged_in": True,
    "iss": "https://accounts.google.com",
    "sub": "123456789",
    "email": OWNER,
    "email_verified": True,
}


@pytest.fixture(autouse=True)
def configure_auth(monkeypatch):
    monkeypatch.setattr(auth.config, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth.config, "AUTH_ALLOWED_EMAILS", OWNER)
    monkeypatch.setattr(auth.st, "secrets", deepcopy(SETTINGS))


def test_allowlist_accepts_verified_google_owner_case_insensitively(monkeypatch):
    monkeypatch.setattr(auth.config, "AUTH_ALLOWED_EMAILS", " OWNER@gmail.com ,second@gmail.com ")
    assert auth.is_authorized_user(IDENTITY)
    assert auth.is_authorized_user(dict(IDENTITY, email="SECOND@gmail.com"))


@pytest.mark.parametrize("changed", [
    {"is_logged_in": False}, {"is_logged_in": "true"},
    {"email": "stranger@gmail.com"}, {"email": "owner@gmail.com.evil.test"},
    {"email": None}, {"email_verified": False}, {"email_verified": "true"},
    {"iss": "https://evil.test"}, {"iss": None}, {"sub": ""}, {"sub": None},
])
def test_untrusted_identity_is_denied(changed):
    assert not auth.is_authorized_user(dict(IDENTITY, **changed))


def test_missing_identity_claims_denied():
    for key in IDENTITY:
        user = dict(IDENTITY)
        del user[key]
        assert not auth.is_authorized_user(user)


@pytest.mark.parametrize("allowlist", ["", "   ", "*", "@gmail.com", "*@gmail.com"])
def test_empty_or_wildcard_allowlist_never_grants_access(monkeypatch, allowlist):
    monkeypatch.setattr(auth.config, "AUTH_ALLOWED_EMAILS", allowlist)
    assert not auth.is_authorized_user(IDENTITY)


def test_allowlist_removal_revokes_existing_identity(monkeypatch):
    assert auth.is_authorized_user(IDENTITY)
    monkeypatch.setattr(auth.config, "AUTH_ALLOWED_EMAILS", "someoneelse@gmail.com")
    assert not auth.is_authorized_user(IDENTITY)


def test_non_google_hosted_email_cannot_rely_on_old_email_verification(monkeypatch):
    monkeypatch.setattr(auth.config, "AUTH_ALLOWED_EMAILS", "owner@example.com")
    assert not auth.is_authorized_user(dict(IDENTITY, email="owner@example.com"))
    assert auth.is_authorized_user(dict(IDENTITY, email="owner@example.com", hd="example.com"))


@pytest.mark.parametrize("uri,expected", [
    ("https://portfolio.example.com/oauth2callback", True),
    ("http://localhost:8501/oauth2callback", True),
    ("http://portfolio.example.com/oauth2callback", False),
    ("https://portfolio.example.com/", False),
    ("https://user:pass@portfolio.example.com/oauth2callback", False),
    ("https://portfolio.example.com/oauth2callback?next=evil", False),
])
def test_callback_configuration_requires_secure_exact_callback(uri, expected):
    auth.st.secrets["auth"]["redirect_uri"] = uri
    assert auth.google_auth_configured() is expected


@pytest.mark.parametrize("key", ["client_id", "client_secret", "server_metadata_url"])
def test_incomplete_provider_blocks_access(key):
    del auth.st.secrets["auth"]["google"][key]
    assert not auth.google_auth_configured()


def test_wrong_provider_and_weak_cookie_secret_block_access():
    auth.st.secrets["auth"]["google"]["server_metadata_url"] = "https://evil.test/config"
    assert not auth.google_auth_configured()
    auth.st.secrets["auth"]["google"]["server_metadata_url"] = auth.GOOGLE_METADATA_URL
    auth.st.secrets["auth"]["cookie_secret"] = "short"
    assert not auth.google_auth_configured()


def test_missing_secrets_block_access(monkeypatch):
    monkeypatch.setattr(auth.st, "secrets", {})
    assert not auth.google_auth_configured()


def _gate(monkeypatch, identity, pressed=False):
    fake = Mock()
    fake.secrets = deepcopy(SETTINGS)
    fake.user = AttrDict(identity)
    fake.button.return_value = pressed
    fake.stop.side_effect = StopException
    fake.session_state = {"auth_ok": True, "auth_ip": "127.0.0.1"}
    monkeypatch.setattr(auth, "st", fake)
    return fake


def test_old_password_session_does_not_bypass_google_login(monkeypatch):
    fake = _gate(monkeypatch, {"is_logged_in": False})
    with pytest.raises(StopException):
        auth.require_auth()
    fake.button.assert_called_once()
    fake.login.assert_not_called()


def test_login_button_calls_native_google_oidc(monkeypatch):
    fake = _gate(monkeypatch, {"is_logged_in": False}, pressed=True)
    with pytest.raises(StopException):
        auth.require_auth()
    fake.login.assert_called_once_with("google")


def test_other_google_account_can_sign_out_but_never_enter(monkeypatch):
    fake = _gate(monkeypatch, dict(IDENTITY, email="stranger@gmail.com"), pressed=True)
    with pytest.raises(StopException):
        auth.require_auth()
    fake.logout.assert_called_once()
    fake.error.assert_called_once()


def test_owner_passes_gate_and_has_logout(monkeypatch):
    fake = _gate(monkeypatch, IDENTITY)
    auth.require_auth()
    fake.stop.assert_not_called()
    fake.sidebar.button.return_value = True
    with pytest.raises(StopException):
        auth.render_account_menu()
    fake.logout.assert_called_once()


def test_missing_configuration_blocks_even_logged_in_owner(monkeypatch):
    fake = _gate(monkeypatch, IDENTITY)
    fake.secrets = {}
    with pytest.raises(StopException):
        auth.require_auth()
    fake.error.assert_called_once()


def test_explicit_local_development_opt_out(monkeypatch):
    fake = _gate(monkeypatch, {"is_logged_in": False})
    monkeypatch.setattr(auth.config, "AUTH_ENABLED", False)
    auth.require_auth()
    fake.stop.assert_not_called()
    fake.login.assert_not_called()


@pytest.mark.parametrize("identity,visible", [
    ({"is_logged_in": False}, False),
    (dict(IDENTITY, email="stranger@gmail.com"), False),
    (IDENTITY, True),
])
def test_streamlit_gate_stops_private_rendering(monkeypatch, identity, visible):
    monkeypatch.setattr(auth.st, "user", AttrDict(identity))
    app = AppTest.from_string('''
import streamlit as st
from app.auth import require_auth
require_auth()
st.markdown("PRIVATE_PORTFOLIO_SENTINEL")
''').run()
    assert not app.exception
    assert any(item.value == "PRIVATE_PORTFOLIO_SENTINEL" for item in app.markdown) is visible


def test_actual_entry_point_blocks_before_database_init(monkeypatch):
    from db import repository

    init = Mock(side_effect=AssertionError("Anonymous request must not initialize the app"))
    monkeypatch.setattr(repository, "init_db", init)
    monkeypatch.setattr(auth.st, "user", AttrDict({"is_logged_in": False}))
    main = Path(__file__).resolve().parents[1] / "app/main.py"
    app = AppTest.from_file(str(main), default_timeout=15).run()
    assert not app.exception
    init.assert_not_called()
    assert any(button.key == "google_login" for button in app.button)
    assert len(app.sidebar.radio) == 0
