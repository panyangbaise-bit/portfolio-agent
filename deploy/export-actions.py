#!/usr/bin/env python3
"""Export the Custom GPT OpenAPI schema without starting services."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a2a.actions import openapi_schema

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--output", default="gpt-actions.openapi.json")
args = parser.parse_args()
url = urlsplit(args.base_url)
if (
    url.scheme != "https"
    or not url.hostname
    or url.port not in (None, 443)
    or url.username
    or url.password
    or url.path not in ("", "/")
    or url.query
    or url.fragment
):
    raise SystemExit("Custom GPT requires an HTTPS origin on port 443")
Path(args.output).write_text(
    json.dumps(openapi_schema(args.base_url), indent=2, ensure_ascii=False) + "\n"
)
print(f"OpenAPI schema saved to {args.output}")
