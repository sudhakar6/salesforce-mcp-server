from __future__ import annotations

import asyncio

import httpx

from .auth import SalesforceAuthError, build_auth
from .config import Settings
from .errors import raise_for_salesforce_error

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5

__all__ = ["SalesforceAuthError", "SalesforceClient"]


class SalesforceClient:
    """Thin async wrapper around Salesforce's REST/Bulk/Composite APIs.

    Handles authentication (Client Credentials Flow or PKCE refresh — see
    `auth/`, picked via `settings.auth_flow`), transparent re-authentication
    on a 401, and retry-with-backoff for transient (5xx or
    REQUEST_LIMIT_EXCEEDED) failures. Endpoint-specific request shapes live in
    the tools/ modules; this class only knows how to talk to Salesforce, not
    what to ask it for — and it doesn't know which auth flow is active
    either, only that `self._auth.get_access_token(http)` returns
    `(access_token, instance_url)` regardless of which one it is.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=60.0)
        self._auth = build_auth(settings)
        self._access_token: str | None = None
        self._instance_url: str | None = None
        self._last_limit_info: str | None = None
        self._org_id: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def last_limit_info(self) -> str | None:
        return self._last_limit_info

    def _versioned_url(self, path: str) -> str:
        return f"{self._instance_url}/services/data/{self._settings.api_version}{path}"

    async def _authenticate(self) -> None:
        self._access_token, self._instance_url = await self._auth.get_access_token(self._http)

    async def request(
        self,
        method: str,
        path: str,
        *,
        versioned: bool = True,
        headers: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Send an authenticated request to Salesforce.

        `path` is versioned-API-relative (e.g. "/query") unless `versioned=False`,
        in which case it's treated as instance-relative — for a path Salesforce
        already returned in full, like a `nextRecordsUrl`
        ("/services/data/v61.0/query/01g...").
        """
        if self._access_token is None:
            await self._authenticate()

        base_headers = dict(headers or {})
        reauthenticated = False
        attempt = 0
        while True:
            attempt += 1
            url = self._versioned_url(path) if versioned else f"{self._instance_url}{path}"
            request_headers = {**base_headers, "Authorization": f"Bearer {self._access_token}"}
            response = await self._http.request(method, url, headers=request_headers, **kwargs)
            self._capture_limit_info(response)

            if response.status_code == 401 and not reauthenticated:
                reauthenticated = True
                await self._authenticate()
                continue

            if self._is_transient(response) and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue

            return response

    async def get_pubsub_auth(self) -> tuple[str, str, str]:
        """Return (access_token, instance_url, org_id) for the Pub/Sub API's
        (gRPC) per-call metadata — a different auth shape than the Bearer
        header `request()` above uses for REST. `org_id` is fetched once via
        SOQL and cached, same pattern as `_access_token`/`_instance_url`.
        """
        if self._access_token is None:
            await self._authenticate()
        if self._org_id is None:
            response = await self.request("GET", "/query", params={"q": "SELECT Id FROM Organization"})
            raise_for_salesforce_error(response)
            records = response.json().get("records", [])
            self._org_id = records[0]["Id"] if records else ""
        return self._access_token, self._instance_url, self._org_id

    def _capture_limit_info(self, response: httpx.Response) -> None:
        limit_info = response.headers.get("Sforce-Limit-Info")
        if limit_info:
            self._last_limit_info = limit_info

    @staticmethod
    def _is_transient(response: httpx.Response) -> bool:
        if response.status_code >= 500:
            return True
        if response.status_code == 403:
            try:
                body = response.json()
            except ValueError:
                return False
            if isinstance(body, list) and body and body[0].get("errorCode") == "REQUEST_LIMIT_EXCEEDED":
                return True
        return False
