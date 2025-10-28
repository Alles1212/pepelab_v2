#!/usr/bin/env python3
"""Reset the MedSSI sandbox state.

Usage:
    python scripts/reset_sandbox.py [base_url] [issuer_token]

Defaults:
    base_url: http://localhost:8000
    issuer_token: koreic2ZEFZ2J4oo2RaZu58yGVXiqDQy

The script issues a POST /v2/api/system/reset request with the supplied token
so developers can quickly start from a clean slate before each demo.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    token = sys.argv[2] if len(sys.argv) > 2 else "koreic2ZEFZ2J4oo2RaZu58yGVXiqDQy"
    url = base_url.rstrip("/") + "/v2/api/system/reset"

    request = urllib.request.Request(url, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, data=b"{}", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        print(f"Reset failed: HTTP {exc.code} – {detail}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Reset failed: {exc.reason}")
        return 1

    timestamp = payload.get("timestamp")
    if timestamp:
        try:
            ts_human = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            formatted = ts_human.strftime("%Y-%m-%d %H:%M:%S %Z")
        except ValueError:
            formatted = timestamp
    else:
        formatted = "unknown"

    print(f"Sandbox reset succeeded at {formatted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
