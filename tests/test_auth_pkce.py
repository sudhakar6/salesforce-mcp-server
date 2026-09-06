from __future__ import annotations

import json
import os

import httpx
import pytest
import respx

from salesforce_mcp.auth.errors import SalesforceAuthError
from salesforce_mcp.auth.pkce import PkceRefreshAuth
from salesforce_mcp.config import Settings
from tests.conftest import INSTANCE_URL, LOGIN_URL

TOKEN_URL = f"{LOGIN_URL}/services/oauth2/token"


@pytest.fixture
def pkce_settings(tmp_path) -> Settings:
    return Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        auth_flow="pkce",
        pkce_token_cache_path=str(tmp_path / "token.json"),
    )


def _write_cache(settings: Settings, refresh_token: str = "refresh-1") -> None:
    with open(settings.pkce_token_cache_path, "w") as f:
        json.dump({"refresh_token": refresh_token, "instance_url": INSTANCE_URL}, f)


async def test_raises_with_clear_message_when_no_cache_exists(pkce_settings):
    auth = PkceRefreshAuth(pkce_settings)
    async with httpx.AsyncClient() as http:
        with pytest.raises(SalesforceAuthError, match="run `python -m salesforce_mcp.login`"):
            await auth.get_access_token(http)


async def test_posts_refresh_token_grant_and_returns_access_token(pkce_settings):
    _write_cache(pkce_settings, refresh_token="refresh-1")
    auth = PkceRefreshAuth(pkce_settings)

    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        route = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "new-access-tok", "instance_url": INSTANCE_URL}
            )
        )
        access_token, instance_url = await auth.get_access_token(http)

    sent_data = dict(x.split("=") for x in route.calls.last.request.content.decode().split("&"))
    assert sent_data["grant_type"] == "refresh_token"
    assert sent_data["refresh_token"] == "refresh-1"
    assert access_token == "new-access-tok"
    assert instance_url == INSTANCE_URL


async def test_rewrites_cache_when_refresh_token_is_rotated(pkce_settings):
    _write_cache(pkce_settings, refresh_token="refresh-old")
    auth = PkceRefreshAuth(pkce_settings)

    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "instance_url": INSTANCE_URL,
                    "refresh_token": "refresh-new",
                },
            )
        )
        await auth.get_access_token(http)

    with open(pkce_settings.pkce_token_cache_path) as f:
        cached = json.load(f)
    assert cached["refresh_token"] == "refresh-new"


async def test_does_not_rewrite_cache_when_refresh_token_unchanged(pkce_settings):
    _write_cache(pkce_settings, refresh_token="refresh-1")
    auth = PkceRefreshAuth(pkce_settings)
    original_mtime = os.stat(pkce_settings.pkce_token_cache_path).st_mtime_ns

    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "tok", "instance_url": INSTANCE_URL, "refresh_token": "refresh-1"}
            )
        )
        await auth.get_access_token(http)

    assert os.stat(pkce_settings.pkce_token_cache_path).st_mtime_ns == original_mtime


async def test_raises_on_non_200(pkce_settings):
    _write_cache(pkce_settings)
    auth = PkceRefreshAuth(pkce_settings)

    async with respx.mock(assert_all_called=True) as router, httpx.AsyncClient() as http:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(SalesforceAuthError, match="invalid_grant"):
            await auth.get_access_token(http)
