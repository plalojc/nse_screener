
# ============================================================
# auth/upstox_auth.py – Upstox daily token refresh helper
# ============================================================
"""
Automates the Upstox OAuth flow so you never manually paste tokens.

Usage:
    python main.py auth

Flow:
    1. Opens the Upstox login page in your browser
    2. Starts a local HTTP callback server (default port 8765)
    3. Upstox redirects to http://127.0.0.1:8765/callback?code=...
    4. Exchanges the code for an access token
    5. Writes UPSTOX_ACCESS_TOKEN to your .env file automatically

Prerequisites – add to .env:
    UPSTOX_CLIENT_ID=<API key from https://account.upstox.com/developer/apps>
    UPSTOX_CLIENT_SECRET=<API secret from same page>
    UPSTOX_REDIRECT_URI=http://127.0.0.1:8765/callback

IMPORTANT: The redirect URI above must be registered in your Upstox app settings
           (Apps → Edit → Redirect URL).  Must match exactly.

Token validity: until 3:30 AM the next day. Run 'python main.py auth' each morning
before the scan, or add it to your daily scheduler.
"""

import os
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from dotenv import set_key

_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
_AUTH_URL  = "https://api.upstox.com/v2/login/authorization/dialog"
_ENV_FILE  = ".env"


def _get_auth_code(port: int) -> str | None:
    """Spin up a one-shot local HTTP server; return the authorization code on callback."""
    code_holder: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                code_holder.append(params["code"][0])
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                    b"<h2 style='color:#2e7d32'>Token refreshed!</h2>"
                    b"<p>You can close this tab and return to your terminal.</p>"
                    b"</body></html>"
                )
            else:
                error = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(
                    f"<html><body><h2>Error: {error}</h2></body></html>".encode()
                )

        def log_message(self, *args):  # silence access logs
            pass

    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 120  # wait up to 2 minutes for the browser callback
    server.handle_request()
    server.server_close()
    return code_holder[0] if code_holder else None


def refresh_token() -> bool:
    """
    Run the full Upstox OAuth flow and write the new token to .env.
    Returns True on success, False on any failure.
    """
    from colorama import Fore, init
    init(autoreset=True)

    client_id     = os.getenv("UPSTOX_CLIENT_ID", "").strip()
    client_secret = os.getenv("UPSTOX_CLIENT_SECRET", "").strip()
    redirect_uri  = os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8765/callback").strip()
    port          = int(os.getenv("UPSTOX_AUTH_PORT", "8765"))

    # ── Validate credentials ──────────────────────────────────────────────
    if not client_id or not client_secret:
        print(Fore.RED + "\n[Auth] Missing Upstox app credentials. Add these to .env:\n")
        print("  UPSTOX_CLIENT_ID=<your API key>")
        print("  UPSTOX_CLIENT_SECRET=<your API secret>")
        print("  UPSTOX_REDIRECT_URI=http://127.0.0.1:8765/callback\n")
        print("Get credentials at: https://account.upstox.com/developer/apps")
        print("Register redirect URI in app settings before running auth.\n")
        return False

    auth_url = (
        f"{_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={quote(client_id, safe='')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
    )

    # ── Open browser ──────────────────────────────────────────────────────
    print(Fore.CYAN + "\n[Auth] Opening Upstox login in your browser...")
    print(f"  Redirect URI : {redirect_uri}")
    print(f"  Callback port: {port}")
    print(f"\n  If the browser doesn't open, visit this URL manually:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # ── Wait for callback ─────────────────────────────────────────────────
    print(Fore.YELLOW + f"[Auth] Waiting for Upstox to redirect back (timeout: 2 min)...")
    code = _get_auth_code(port)

    if not code:
        print(Fore.RED + "[Auth] No authorization code received (timed out or browser error).")
        return False

    print("[Auth] Authorization code received. Exchanging for access token...")

    # ── Exchange code for token ───────────────────────────────────────────
    try:
        resp = requests.post(
            _TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            data={
                "code":          code,
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        print(Fore.RED + f"[Auth] Network error during token exchange: {exc}")
        return False

    if resp.status_code != 200:
        print(Fore.RED + f"[Auth] Token exchange failed ({resp.status_code}): {resp.text}")
        return False

    payload = resp.json()
    # Upstox wraps the token under data.access_token
    token_data = payload.get("data", payload)
    token = token_data.get("access_token", "")

    if not token:
        print(Fore.RED + f"[Auth] access_token missing in response: {resp.text}")
        return False

    # ── Write new token to .env ───────────────────────────────────────────
    set_key(_ENV_FILE, "UPSTOX_ACCESS_TOKEN", token)

    user_name = token_data.get("user_name", "")
    user_info = f" ({user_name})" if user_name else ""
    print(Fore.GREEN + f"[Auth] Token saved to {_ENV_FILE}{user_info}.")
    print(Fore.GREEN + "[Auth] Valid until 3:30 AM tomorrow.")
    print(Fore.CYAN  + "[Auth] Run 'python main.py scan' to start scanning.\n")
    return True
