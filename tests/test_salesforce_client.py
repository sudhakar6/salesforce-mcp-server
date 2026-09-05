from __future__ import annotations

import asyncio

import httpx
import respx

from salesforce_mcp.salesforce_client import SalesforceAuthError, SalesforceClient
from tests.conftest import DATA_BASE, INSTANCE_URL, LOGIN_URL

TOKEN_URL = f"{LOGIN_URL}/services/oauth2/token"
LIMITS_URL = f"{DATA_BASE}/limits"


def _mock_auth(router, token: str = "tok-1"):
    return router.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": token, "instance_url": INSTANCE_URL})
    )


async def test_authenticates_lazily_and_reuses_the_token(settings):
    client = SalesforceClient(settings)
    async with respx.mock(assert_all_called=True) as router:
        auth_route = _mock_auth(router)
        limits_route = router.get(LIMITS_URL).mock(return_value=httpx.Response(200, json={}))

        await client.request("GET", "/limits")
        await client.request("GET", "/limits")

    assert auth_route.call_count == 1
    assert limits_route.call_count == 2
    await client.aclose()


async def test_authentication_failure_raises_salesforce_auth_error(settings):
    client = SalesforceClient(settings)
    async with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
        try:
            await client.request("GET", "/limits")
        except SalesforceAuthError as exc:
            assert "invalid_client" in str(exc)
        else:
            raise AssertionError("expected SalesforceAuthError")
    await client.aclose()


async def test_reauthenticates_once_on_401(authed_client):
    async with respx.mock(assert_all_called=True) as router:
        auth_route = _mock_auth(router, token="tok-2")
        limits_route = router.get(LIMITS_URL).mock(
            side_effect=[
                httpx.Response(401, json=[{"errorCode": "INVALID_SESSION_ID"}]),
                httpx.Response(200, json={}),
            ]
        )

        response = await authed_client.request("GET", "/limits")

    assert response.status_code == 200
    assert auth_route.call_count == 1
    assert limits_route.call_count == 2


async def test_retries_5xx_with_backoff_then_succeeds(authed_client, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async with respx.mock(assert_all_called=True) as router:
        limits_route = router.get(LIMITS_URL).mock(
            side_effect=[
                httpx.Response(503, text="Service Unavailable"),
                httpx.Response(200, json={}),
            ]
        )
        response = await authed_client.request("GET", "/limits")

    assert response.status_code == 200
    assert limits_route.call_count == 2
    assert len(sleeps) == 1


async def test_retries_request_limit_exceeded_then_gives_up_after_max_attempts(authed_client, monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    limit_exceeded = httpx.Response(403, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "limit"}])

    async with respx.mock(assert_all_called=True) as router:
        limits_route = router.get(LIMITS_URL).mock(return_value=limit_exceeded)
        response = await authed_client.request("GET", "/limits")

    assert response.status_code == 403
    assert limits_route.call_count == 3  # MAX_ATTEMPTS, no further retry after that


async def test_does_not_retry_plain_4xx_errors(authed_client):
    async with respx.mock(assert_all_called=True) as router:
        limits_route = router.get(LIMITS_URL).mock(
            return_value=httpx.Response(400, json=[{"errorCode": "MALFORMED_QUERY", "message": "bad"}])
        )
        response = await authed_client.request("GET", "/limits")

    assert response.status_code == 400
    assert limits_route.call_count == 1


async def test_captures_sforce_limit_info_header(authed_client):
    async with respx.mock(assert_all_called=True) as router:
        router.get(LIMITS_URL).mock(
            return_value=httpx.Response(200, json={}, headers={"Sforce-Limit-Info": "api-usage=42/15000"})
        )
        await authed_client.request("GET", "/limits")

    assert authed_client.last_limit_info == "api-usage=42/15000"


async def test_versioned_false_treats_path_as_instance_relative(authed_client):
    next_page_url = f"{INSTANCE_URL}/services/data/v61.0/query/01g-next"
    async with respx.mock(assert_all_called=True) as router:
        route = router.get(next_page_url).mock(return_value=httpx.Response(200, json={"records": []}))
        response = await authed_client.request(
            "GET", "/services/data/v61.0/query/01g-next", versioned=False
        )

    assert response.status_code == 200
    assert route.call_count == 1
