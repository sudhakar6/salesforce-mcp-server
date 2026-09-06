from __future__ import annotations

import httpx
import pytest
import respx

from salesforce_mcp.auth.client_credentials import ClientCredentialsAuth
from salesforce_mcp.auth.errors import SalesforceAuthError
from tests.conftest import INSTANCE_URL, LOGIN_URL

TOKEN_URL = f"{LOGIN_URL}/services/oauth2/token"


async def test_get_access_token_posts_client_credentials_grant(settings):
    auth = ClientCredentialsAuth(settings)
    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        route = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "instance_url": INSTANCE_URL})
        )
        access_token, instance_url = await auth.get_access_token(http)

    sent = route.calls.last.request
    sent_data = dict(x.split("=") for x in sent.content.decode().split("&"))
    assert sent_data["grant_type"] == "client_credentials"
    assert sent_data["client_id"] == settings.client_id
    assert access_token == "tok-1"
    assert instance_url == INSTANCE_URL


async def test_get_access_token_raises_on_non_200(settings):
    auth = ClientCredentialsAuth(settings)
    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
        with pytest.raises(SalesforceAuthError, match="invalid_client"):
            await auth.get_access_token(http)
