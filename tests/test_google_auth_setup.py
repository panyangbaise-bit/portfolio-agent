"""Deployment migration must preserve API secrets and private file permissions."""
import importlib.util
from pathlib import Path
import stat

from dotenv import dotenv_values
import pytest
import tomlkit

spec = importlib.util.spec_from_file_location(
    "google_setup", Path(__file__).resolve().parents[1] / "deploy/configure-google-auth.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_setup_preserves_other_settings_and_removes_password(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AUTH_PASSWORD=obsolete\nAUTH_MAX_FAILURES=3\nA2A_TOKEN=keep-api-secret\nDEEPSEEK_API_KEY=keep-model-secret\n")
    directory = tmp_path / ".streamlit"
    directory.mkdir()
    path = directory / "secrets.toml"
    path.write_text('[unrelated]\nvalue = "preserved"\n')
    setup.configure(tmp_path, "https://portfolio.example.com", "Owner@gmail.com", "test.apps.googleusercontent.com", "client-secret")
    values = dotenv_values(env)
    assert values["AUTH_ENABLED"] == "true"
    assert values["AUTH_ALLOWED_EMAILS"] == "owner@gmail.com"
    assert "AUTH_PASSWORD" not in values
    assert "AUTH_MAX_FAILURES" not in values
    assert values["A2A_TOKEN"] == "keep-api-secret"
    assert values["DEEPSEEK_API_KEY"] == "keep-model-secret"
    doc = tomlkit.parse(path.read_text())
    assert doc["unrelated"]["value"] == "preserved"
    assert doc["auth"]["redirect_uri"] == "https://portfolio.example.com/oauth2callback"
    assert doc["auth"]["google"]["client_secret"] == "client-secret"
    assert len(doc["auth"]["cookie_secret"]) >= 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    cookie = doc["auth"]["cookie_secret"]
    setup.configure(tmp_path, "https://portfolio.example.com", "owner@gmail.com", "test.apps.googleusercontent.com", "new-secret")
    assert tomlkit.parse(path.read_text())["auth"]["cookie_secret"] == cookie
    setup.configure(tmp_path, "https://portfolio.example.com", "owner@gmail.com", "other.apps.googleusercontent.com", "new-secret")
    assert tomlkit.parse(path.read_text())["auth"]["cookie_secret"] != cookie


@pytest.mark.parametrize("origin", [
    "http://portfolio.example.com", "https://portfolio.example.com/path",
    "https://user:password@portfolio.example.com", "https://portfolio.example.com?x=1",
    "https://portfolio.example.com#fragment", "javascript:alert(1)",
])
def test_reject_bad_origins(origin):
    with pytest.raises(ValueError):
        setup.callback_url(origin)


def test_allow_local_development_callback():
    assert setup.callback_url("http://localhost:8501/") == "http://localhost:8501/oauth2callback"


@pytest.mark.parametrize("email", ["*", "*@gmail.com", "owner@gmail.com,other@gmail.com", ""])
def test_invalid_allowlist_does_not_change_files(tmp_path, email):
    env = tmp_path / ".env"
    env.write_text("A2A_TOKEN=keep\n")
    with pytest.raises(ValueError):
        setup.configure(tmp_path, "https://portfolio.example.com", email, "test.apps.googleusercontent.com", "secret")
    assert env.read_text() == "A2A_TOKEN=keep\n"
    assert not (tmp_path / ".streamlit" / "secrets.toml").exists()
