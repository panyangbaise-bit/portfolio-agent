#!/usr/bin/env python3
"""Launch the downloaded bridge with only the A2A secret from the local .env."""

import argparse
import os
from pathlib import Path

from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--node", required=True)
parser.add_argument("--bridge", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
token = os.environ.get("PORTFOLIO_A2A_TOKEN") or dotenv_values(root / ".env").get("A2A_TOKEN")
if not token:
    raise SystemExit("Set A2A_TOKEN in portfolio-agent/.env before launching the bridge")
env = dict(os.environ, PORTFOLIO_A2A_TOKEN=token, A2A_MCP_CONFIG=args.config)
os.execve(args.node, [args.node, args.bridge], env)
