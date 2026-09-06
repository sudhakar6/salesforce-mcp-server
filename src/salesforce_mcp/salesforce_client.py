from __future__ import annotations

import asyncio

import httpx

from .config import Settings
from .errors import raise_for_salesforce_error

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5


class SalesforceAuthError(RuntimeError):
    """Raised when authenticating to Salesforce fails."""


class SalesforceClient:
    """Thin async wrapper around Salesforce's REST/Bulk/Composite APIs.

    Handles OAuth 2.0 Client Credentials Flow authentication, transparent
    re-authentication on a 401, and retry-with-backoff for transient (5xx or
    REQUEST_LIMIT_EXCEEDED) failures. Endpoint-specific request shapes live in
    the tools/ modules; this class only knows how to talk to Salesforce, not
    what to ask it for.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=60.0)
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
        response = await self._http.post(
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
        self._access_token = body["access_token"]
        self._instance_url = body["instance_url"]

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
