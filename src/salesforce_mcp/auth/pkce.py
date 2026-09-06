from __future__ import annotations

import json
from pathlib import Path

import httpx

from ..config import Settings
from .errors import SalesforceAuthError


class PkceRefreshAuth:
    """OAuth 2.0 Authorization Code + PKCE Flow — refresh-only side.

    The interactive part (opening a browser, catching the redirect, the
    initial code-for-token exchange) lives entirely in `login.py`, run once
    manually ahead of time. This class only ever does the cheap, silent
    part: read the refresh token that login left on disk, and exchange it
    for a fresh access token — the same shape `get_access_token()` returns
    for every auth flow, so SalesforceClient doesn't need to know which one
    is active.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    async def get_access_token(self, http: httpx.AsyncClient) -> tuple[str, str]:
        cache_path = Path(self._settings.pkce_token_cache_path)
        if not cache_path.exists():
            raise SalesforceAuthError(
                f"No cached PKCE login found at {cache_path} — run "
                "`python -m salesforce_mcp.login` first, then set SF_AUTH_FLOW=pkce."
            )
        cached = json.loads(cache_path.read_text())

        data = {
            "grant_type": "refresh_token",
            "client_id": self._settings.client_id,
            "refresh_token": cached["refresh_token"],
        }
        if self._settings.client_secret:
            data["client_secret"] = self._settings.client_secret

        response = await http.post(f"{self._settings.login_url}/services/oauth2/token", data=data)
        if response.status_code != 200:
            raise SalesforceAuthError(
                f"Salesforce PKCE token refresh failed ({response.status_code}): {response.text}"
            )
        body = response.json()

        # Salesforce may rotate the refresh token on use; if it did, the old
        # one is now invalid, so the cache must be updated or the *next*
        # refresh will fail even though this one just succeeded.
        new_refresh_token = body.get("refresh_token")
        if new_refresh_token and new_refresh_token != cached["refresh_token"]:
            cache_path.write_text(
                json.dumps({"refresh_token": new_refresh_token, "instance_url": body["instance_url"]})
            )
            cache_path.chmod(0o600)

        return body["access_token"], body.get("instance_url", cached.get("instance_url"))
