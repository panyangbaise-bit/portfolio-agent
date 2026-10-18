#!/usr/bin/env python3
"""Install the pinned upstream MCP bridge and optionally register it in Codex."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE = "@cognicellai/a2a-mcp@0.1.1"


def find_codex_cli():
    executable = shutil.which("codex")
    if executable:
        return executable
    # Desktop apps bundle the CLI even when the user's shell PATH lacks it.
    for applications in (Path("/Applications"), Path.home() / "Applications"):
        for relative in (
            "Codex.app/Contents/Resources/codex",
            "ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
        ):
            candidate = applications / relative
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8502")
parser.add_argument("--codex", action="store_true", help="Register a2a-bridge in Codex")
parser.add_argument(
    "--allow-http",
    action="store_true",
    help="Allow remote plaintext HTTP; token and portfolio data will not be encrypted",
)
args = parser.parse_args()
base = args.base_url.rstrip("/")
url = urlsplit(base)
local = url.hostname in {"localhost", "127.0.0.1", "::1"}
if (
    url.scheme not in {"http", "https"}
    or not url.hostname
    or url.username
    or url.password
    or url.path not in {"", "/"}
    or url.query
    or url.fragment
):
    raise SystemExit("Use an HTTP(S) origin without credentials/path/query/fragment")
if not local and url.scheme == "http":
    if not args.allow_http:
        raise SystemExit(
            "Remote HTTP requires --allow-http (token and data are sent unencrypted); HTTPS is supported without this flag"
        )
    print(
        "Remote HTTP enabled: bearer token and portfolio data are sent unencrypted.",
        file=sys.stderr,
    )
node, npm = shutil.which("node"), shutil.which("npm")
if not node or not npm:
    raise SystemExit("Node.js 20+ and npm are required")
install = Path.home() / ".local/share/portfolio-agent-a2a"
subprocess.run(
    [npm, "install", "--prefix", str(install), "--ignore-scripts", "--save-exact", PACKAGE],
    check=True,
)
config_dir = Path.home() / ".config/portfolio-agent"
config_dir.mkdir(parents=True, exist_ok=True)
config_path = config_dir / "a2a-mcp.json"
config_path.write_text(
    json.dumps(
        {
            "agents": {
                "portfolio": {
                    "cardUrl": base + "/a2a/v1/.well-known/agent-card.json",
                    "allowedBindings": ["JSONRPC"],
                    "authProfile": "portfolio",
                    "signaturePolicy": "ifPresent",
                    "directUrlPolicy": "disabled",
                }
            },
            "authProfiles": {"portfolio": {"type": "bearer-env", "env": "PORTFOLIO_A2A_TOKEN"}},
            "network": {
                "allowPrivateAddresses": local,
                "requireHttps": not local and url.scheme == "https",
                "timeoutMs": 30000,
                "maxResponseBytes": 1048576,
            },
        },
        indent=2,
    )
    + "\n"
)
config_path.chmod(0o600)
root = Path(__file__).resolve().parents[1]
command = [
    sys.executable,
    str(root / "deploy/run-a2a-mcp.py"),
    "--config",
    str(config_path),
    "--node",
    node,
    "--bridge",
    str(install / "node_modules/@cognicellai/a2a-mcp/dist/index.js"),
]
if args.codex:
    codex = find_codex_cli()
    if not codex:
        print(
            json.dumps(
                {"package": PACKAGE, "config": str(config_path), "command": command}, indent=2
            )
        )
        raise SystemExit(
            "Bridge installed; codex CLI not found in PATH or desktop apps. Use the command array above to register this stdio server in your MCP client."
        )
    current = Path.home() / ".codex/config.toml"
    if current.exists():
        from datetime import datetime

        shutil.copy2(
            current,
            current.with_name("config.toml.before-a2a-" + datetime.now().strftime("%Y%m%d%H%M%S")),
        )
    subprocess.run([codex, "mcp", "add", "a2a-bridge", "--", *command], check=True)
print(json.dumps({"package": PACKAGE, "config": str(config_path), "command": command}, indent=2))
