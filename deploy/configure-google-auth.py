#!/usr/bin/env python3
"""Configure Google login without exposing secrets in shell history or output."""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import re
import secrets
import tempfile
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key, unset_key
import tomlkit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGIN = "https://portfolio.panyang666.com"


def callback_url(origin: str) -> str:
    origin = origin.rstrip("/")
    url = urlsplit(origin)
    if (not url.hostname or url.username or url.password or url.path or url.query or url.fragment
            or not (url.scheme == "https" or
                    (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))):
        raise ValueError("Use an HTTPS origin, or HTTP localhost for development")
    return origin + "/oauth2callback"


def configure(root: Path, origin: str, email: str, client_id: str, client_secret: str) -> None:
    redirect = callback_url(origin)
    email = email.strip().lower()
    if not re.fullmatch(r"[^\s@,*]+@[^\s@,*]+\.[^\s@,*]+", email):
        raise ValueError("Enter one exact Google account email, without wildcards")
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        raise ValueError("A Google Web client ID and a nonempty Client Secret are required")
    env_path = root / ".env"
    if not env_path.is_file():
        raise ValueError("Create .env from .env.example and configure your model first")
    env_stat = env_path.stat()
    path = root / ".streamlit" / "secrets.toml"
    document = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
    old_auth = document.get("auth", {})
    # Preserve sessions on ordinary reruns; changing clients invalidates cookies.
    cookie = old_auth.get("cookie_secret", "")
    if (not isinstance(cookie, str) or len(cookie) < 32
            or old_auth.get("google", {}).get("client_id") != client_id):
        cookie = secrets.token_urlsafe(48)
    document["auth"] = {
        "redirect_uri": redirect,
        "cookie_secret": cookie,
        "google": {
            "client_id": client_id,
            "client_secret": client_secret,
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid email profile", "prompt": "select_account"},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".google-auth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(tomlkit.dumps(document))
        os.chmod(temporary, 0o600)
        if os.geteuid() == 0:
            os.chown(temporary, env_stat.st_uid, env_stat.st_gid)
            os.chown(path.parent, env_stat.st_uid, env_stat.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # Keep all model and A2A settings; remove obsolete password material.
    old_values = dotenv_values(env_path)
    env_path.chmod(0o600)
    try:
        set_key(env_path, "AUTH_ENABLED", "true")
        set_key(env_path, "AUTH_ALLOWED_EMAILS", email)
        for key in ("AUTH_PASSWORD", "AUTH_MAX_FAILURES"):
            if key in old_values:
                unset_key(env_path, key)
    finally:
        env_path.chmod(0o600)
        if os.geteuid() == 0:
            os.chown(env_path, env_stat.st_uid, env_stat.st_gid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_ORIGIN)
    parser.add_argument("--email", help="The one Gmail / Google Workspace account allowed to access the UI")
    parser.add_argument("--project-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    email = args.email or input("Allowed Google email: ")
    client_id = input("Google Web Client ID: ")
    client_secret = getpass("Google Client Secret (hidden): ")
    try:
        configure(args.project_dir, args.base_url, email, client_id, client_secret)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    print("Google login configured. Existing A2A/model settings preserved; old UI password removed.")
    print("Redirect URI:", callback_url(args.base_url))
    print("Restart portfolio-agent, then test login using your allowed account.")


if __name__ == "__main__":
    main()
