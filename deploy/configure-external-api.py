#!/usr/bin/env python3
"""Configure loopback API and private tokens without printing credentials."""
import argparse
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key

parser = argparse.ArgumentParser()
parser.add_argument("--base-url")
parser.add_argument("--a2a-only", action="store_true", help="Enable A2A, preserve existing endpoints, leave Actions unchanged")
parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
args = parser.parse_args()
path = args.env_file
if not path.exists():
    raise SystemExit("Create .env from .env.example and configure the model first")
values = dotenv_values(path)
port = (values.get("A2A_PORT") or "8502") if args.a2a_only else "8502"
base = args.base_url
if not base:
    base = (values.get("A2A_PUBLIC_URL") if args.a2a_only else None) or f"http://127.0.0.1:{port}"
base = base.rstrip("/")
url = urlsplit(base)
if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
        or url.path not in {"", "/"} or url.query or url.fragment):
    raise SystemExit("Use an origin URL, e.g. https://portfolio.example.com")
if not args.a2a_only and url.hostname not in {"127.0.0.1", "localhost", "::1"} and (url.scheme != "https" or url.port not in {None, 443}):
    raise SystemExit("Public GPT Actions require HTTPS on port 443")
path.chmod(0o600)
for key in (("A2A_TOKEN",) if args.a2a_only else ("A2A_TOKEN", "ACTIONS_TOKEN")):
    if not values.get(key):
        set_key(path, key, secrets.token_urlsafe(32))
updates = {
    "A2A_ENABLED": "true", "A2A_PORT": port, "A2A_PUBLIC_URL": base,
    "A2A_HOST": (values.get("A2A_HOST") or "127.0.0.1") if args.a2a_only else "127.0.0.1",
}
if not args.a2a_only:
    updates.update(ACTIONS_ENABLED="true", ACTIONS_PUBLIC_URL=base)
for key, value in updates.items():
    set_key(path, key, value)
path.chmod(0o600)
print(f"Configured external API at {base}; private tokens stored in {path}. Existing tokens preserved.")
