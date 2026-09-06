from __future__ import annotations

import httpx

from ..config import Settings
from .errors import SalesforceAuthError


class ClientCredentialsAuth:
    """OAuth 2.0 Client Credentials Flow — one fixed Salesforce identity
    (the integration user configured on the External Client App), shared by
    every caller of this server. No user interaction; a single POST per
    (re-)authentication.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    async def get_access_token(self, http: httpx.AsyncClient) -> tuple[str, str]:
        response = await http.post(
            f"{self._settings.login_url}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
            },
        )
        if response.status_code != 200:
            raise SalesforceAuthError(
                f"Salesforce authentication failed ({response.status_code}): {response.text}"
            )
        body = response.json()
        return body["access_token"], body["instance_url"]
