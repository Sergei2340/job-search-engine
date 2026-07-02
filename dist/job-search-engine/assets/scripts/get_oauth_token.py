"""Mint oauth_token.json (refresh token, Sheets scope) for the pipeline.

One-time, interactive, run on the machine that owns the pipeline:

    python scripts/get_oauth_token.py --profile <dept>

Prerequisites:
- profiles/<dept>/oauth_client.json — an OAuth "Desktop app" client JSON
  downloaded from Google Cloud Console (or given to you by the pipeline
  owner). Format: {"installed": {"client_id": ..., "client_secret": ...}}.
- A browser on this machine; you will approve access for the Google account
  that owns the target sheet.

Writes profiles/<dept>/oauth_token.json: {"refresh_token": ...,
"token_uri": "https://oauth2.googleapis.com/token", "scopes": [...]}.

Stdlib + requests only (no google-auth dependency).
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 8765

_code_holder: dict = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        if "code" in params and params.get("state", [""])[0] == _code_holder.get("state"):
            _code_holder["code"] = params["code"][0]
            body = b"<h2>Authorized. You can close this tab and return to the terminal.</h2>"
        else:
            body = b"<h2>Missing or invalid code/state. Retry the script.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence request logging
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="Department profile name under profiles/")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    profile_dir = repo / "profiles" / args.profile
    client_path = profile_dir / "oauth_client.json"
    token_path = profile_dir / "oauth_token.json"

    if not client_path.exists():
        print(f"ERROR: {client_path} not found. Download an OAuth 'Desktop app' client "
              "JSON from Google Cloud Console (APIs & Services -> Credentials) and save "
              "it there first. See the setup guide.")
        return 2

    installed = json.loads(client_path.read_text()).get("installed") or {}
    client_id, client_secret = installed.get("client_id"), installed.get("client_secret")
    if not client_id or not client_secret:
        print("ERROR: oauth_client.json must contain installed.client_id and "
              "installed.client_secret (a 'Desktop app' OAuth client).")
        return 2

    redirect_uri = f"http://localhost:{PORT}"
    state = secrets.token_urlsafe(16)
    _code_holder["state"] = state
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",        # force a refresh_token even on re-auth
        "state": state,
    })

    server = http.server.HTTPServer(("localhost", PORT), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("Opening browser for Google authorization…\nIf it does not open, visit:\n" + auth_url)
    webbrowser.open(auth_url)

    print(f"Waiting for the redirect on {redirect_uri} …")
    while "code" not in _code_holder:
        pass  # handle_request returns after one request; loop is belt-and-braces

    r = requests.post(TOKEN_URL, data={
        "code": _code_holder["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    refresh = tok.get("refresh_token")
    if not refresh:
        print("ERROR: no refresh_token in response (was consent screen skipped?). "
              "Remove prior grants at https://myaccount.google.com/permissions and retry.")
        return 3

    token_path.write_text(json.dumps({
        "refresh_token": refresh,
        "token_uri": TOKEN_URL,
        "scopes": [SCOPE],
    }, indent=2))
    print(f"OK: wrote {token_path} (keep it secret; it grants write access to your sheets).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
