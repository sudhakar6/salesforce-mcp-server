"""Interactive PKCE login — as a one-time CLI command, or importable for
`tools/sf_login.py` to call from a live server.

Run manually, once, in a terminal: `python -m salesforce_mcp.login`

Opens your browser to Salesforce's login/consent page, catches the redirect
on a temporary local HTTP listener, exchanges the resulting code for tokens,
and caches the refresh token to disk (SF_PKCE_TOKEN_CACHE, default
.salesforce_pkce_token.json) for `auth/pkce.py`'s PkceRefreshAuth to use
later.

Deliberately does not import anything from auth/pkce.py or
auth/client_credentials.py: this script and PkceRefreshAuth only agree on
the on-disk JSON shape ({"refresh_token", "instance_url"}), not on code.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import webbrowser
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .auth.errors import SalesforceAuthError
from .config import Settings

CALLBACK_TIMEOUT_SECONDS = 120
_POLL_INTERVAL_SECONDS = 5


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). Verifier is 96 random bytes,
    base64url-encoded unpadded — within RFC 7636's 43-128 char bound.
    Challenge is the S256 method: base64url(sha256(verifier))."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    challenge = challenge.rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    *, login_url: str, client_id: str, redirect_uri: str, code_challenge: str, state: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{login_url}/services/oauth2/authorize?{urllib.parse.urlencode(params)}"


class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def _wait_for_callback(port: int) -> _CallbackResult:
    """Blocking — run this via asyncio.to_thread(...) from async code, never
    directly, or it freezes the caller's whole event loop until a redirect
    arrives (up to CALLBACK_TIMEOUT_SECONDS)."""
    result = _CallbackResult()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silence default request logging
            pass

        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urlparse(self.path).query)
            result.code = query.get("code", [None])[0]
            result.state = query.get("state", [None])[0]
            result.error = query.get("error_description", query.get("error", [None]))[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            message = "Login complete — you can close this tab." if result.code else "Login failed."
            self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

    server = http.server.HTTPServer(("localhost", port), Handler)
    server.timeout = CALLBACK_TIMEOUT_SECONDS
    server.handle_request()
    server.server_close()
    return result


async def _noop_status(_message: str) -> None:
    pass


async def perform_interactive_login(
    settings: Settings,
    *,
    on_status: Callable[[str], Awaitable[None]] | None = None,
    wait_for_callback: Callable[[int], _CallbackResult] = _wait_for_callback,
    generate_state: Callable[[], str] = lambda: secrets.token_urlsafe(16),
) -> dict:
    """Run the full interactive PKCE flow; returns {"instance_url", "cache_path"}.

    Raises SalesforceAuthError on any failure (timeout, state mismatch,
    Salesforce login error, token exchange failure) — never sys.exit(),
    since this is shared between the CLI (`main()`, below) and the
    `sf_login` tool, which needs a real exception `@as_tool_error` can
    translate into a clean message.

    The blocking callback listener runs in a worker thread
    (`asyncio.to_thread`) so this coroutine — and the event loop it's
    running on — stays responsive to any other concurrent request for the
    whole time it's waiting on you to complete the login in your browser.
    `on_status`, if given, is awaited with a short message at each
    milestone, including every `_POLL_INTERVAL_SECONDS` while waiting —
    the CLI prints them, `sf_login` relays them via `ctx.report_progress()`.
    `wait_for_callback`/`generate_state` are injectable for tests only —
    real callers should never need to pass either.
    """
    status = on_status or _noop_status

    verifier, challenge = generate_pkce_pair()
    state = generate_state()
    redirect_uri = f"http://localhost:{settings.pkce_redirect_port}/callback"
    authorize_url = build_authorize_url(
        login_url=settings.login_url,
        client_id=settings.client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
    )

    await status(f"Opening your browser to log in to Salesforce: {authorize_url}")
    webbrowser.open(authorize_url)

    callback_task = asyncio.ensure_future(asyncio.to_thread(wait_for_callback, settings.pkce_redirect_port))
    waited = 0
    while not callback_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(callback_task), timeout=_POLL_INTERVAL_SECONDS)
        except TimeoutError:
            waited += _POLL_INTERVAL_SECONDS
            await status(
                f"Waiting for you to complete login in your browser... ({waited}s elapsed, "
                f"{CALLBACK_TIMEOUT_SECONDS}s timeout)"
            )
    result = callback_task.result()

    if result.error:
        raise SalesforceAuthError(f"Login failed: {result.error}")
    if not result.code:
        raise SalesforceAuthError(
            f"Timed out after {CALLBACK_TIMEOUT_SECONDS}s waiting for the Salesforce redirect."
        )
    if result.state != state:
        raise SalesforceAuthError("Login aborted: the callback's state did not match — possible CSRF.")

    token_data = {
        "grant_type": "authorization_code",
        "code": result.code,
        "client_id": settings.client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    if settings.client_secret:
        token_data["client_secret"] = settings.client_secret

    await status("Exchanging code for tokens...")
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(f"{settings.login_url}/services/oauth2/token", data=token_data)
    if response.status_code != 200:
        raise SalesforceAuthError(f"Token exchange failed ({response.status_code}): {response.text}")
    body = response.json()

    cache_path = Path(settings.pkce_token_cache_path)
    cache_path.write_text(
        json.dumps({"refresh_token": body["refresh_token"], "instance_url": body["instance_url"]})
    )
    cache_path.chmod(0o600)

    await status(f"Logged in to {body['instance_url']}.")
    return {"instance_url": body["instance_url"], "cache_path": str(cache_path)}


def main() -> None:
    settings = Settings.from_env()

    async def _print_status(message: str) -> None:
        print(message)

    try:
        result = asyncio.run(perform_interactive_login(settings, on_status=_print_status))
    except SalesforceAuthError as exc:
        sys.exit(str(exc))

    print(f"Cached refresh token to {result['cache_path']} (chmod 600).")
    print("Run the server with SF_AUTH_FLOW=pkce to use it (already the default).")


if __name__ == "__main__":
    main()
