from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse

import httpx
import pytest
import respx

from salesforce_mcp.auth.errors import SalesforceAuthError
from salesforce_mcp.config import Settings
from salesforce_mcp.login import (
    _CallbackResult,
    build_authorize_url,
    generate_pkce_pair,
    perform_interactive_login,
)
from tests.conftest import INSTANCE_URL, LOGIN_URL

TOKEN_URL = f"{LOGIN_URL}/services/oauth2/token"
FIXED_STATE = "fixed-state-for-tests"


@pytest.fixture
def login_settings(tmp_path) -> Settings:
    return Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        pkce_token_cache_path=str(tmp_path / "token.json"),
    )


def _instant_callback(code: str = "auth-code-1", state: str = FIXED_STATE, error: str | None = None):
    def _wait_for_callback(port: int) -> _CallbackResult:
        result = _CallbackResult()
        result.code = code
        result.state = state
        result.error = error
        return result

    return _wait_for_callback


def test_generate_pkce_pair_verifier_length_within_rfc7636_bounds():
    verifier, _ = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_generate_pkce_pair_challenge_is_s256_of_verifier():
    verifier, challenge = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    expected = expected.rstrip(b"=").decode("ascii")
    assert challenge == expected


def test_generate_pkce_pair_is_unique_per_call():
    verifier1, _ = generate_pkce_pair()
    verifier2, _ = generate_pkce_pair()
    assert verifier1 != verifier2


def test_build_authorize_url_has_expected_query_params():
    url = build_authorize_url(
        login_url="https://example.my.salesforce.com",
        client_id="client-123",
        redirect_uri="http://localhost:8765/callback",
        code_challenge="challenge-abc",
        state="state-xyz",
    )

    base, _, query = url.partition("?")
    params = urllib.parse.parse_qs(query)

    assert base == "https://example.my.salesforce.com/services/oauth2/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["http://localhost:8765/callback"]
    assert params["code_challenge"] == ["challenge-abc"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["state-xyz"]


async def test_perform_interactive_login_writes_cache_and_returns_instance_url(login_settings):
    statuses: list[str] = []

    async def on_status(message: str) -> None:
        statuses.append(message)

    async with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "tok", "refresh_token": "refresh-1", "instance_url": INSTANCE_URL}
            )
        )
        result = await perform_interactive_login(
            login_settings,
            on_status=on_status,
            wait_for_callback=_instant_callback(),
            generate_state=lambda: FIXED_STATE,
        )

    assert result["instance_url"] == INSTANCE_URL
    assert result["cache_path"] == login_settings.pkce_token_cache_path

    with open(login_settings.pkce_token_cache_path) as f:
        cached = json.load(f)
    assert cached == {"refresh_token": "refresh-1", "instance_url": INSTANCE_URL}

    assert any("Opening your browser" in s for s in statuses)
    assert any("Logged in to" in s for s in statuses)


async def test_perform_interactive_login_raises_on_state_mismatch(login_settings):
    with pytest.raises(SalesforceAuthError, match="state did not match"):
        await perform_interactive_login(
            login_settings,
            wait_for_callback=_instant_callback(state="a-different-state"),
            generate_state=lambda: FIXED_STATE,
        )


async def test_perform_interactive_login_raises_on_callback_error(login_settings):
    with pytest.raises(SalesforceAuthError, match="Login failed: access_denied"):
        await perform_interactive_login(
            login_settings,
            wait_for_callback=_instant_callback(code=None, error="access_denied"),
            generate_state=lambda: FIXED_STATE,
        )


async def test_perform_interactive_login_raises_on_token_exchange_failure(login_settings):
    async with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(SalesforceAuthError, match="invalid_grant"):
            await perform_interactive_login(
                login_settings,
                wait_for_callback=_instant_callback(),
                generate_state=lambda: FIXED_STATE,
            )
