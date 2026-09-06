from __future__ import annotations

import json

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer

from salesforce_mcp.config import Settings
from salesforce_mcp.server import build_server
from salesforce_mcp.tools import sf_login as sf_login_module
from tests.conftest import INSTANCE_URL, LOGIN_URL, FakeContext

TOKEN_URL = f"{LOGIN_URL}/services/oauth2/token"


@pytest.fixture
def pkce_settings(tmp_path) -> Settings:
    return Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        auth_flow="pkce",
        pkce_token_cache_path=str(tmp_path / "token.json"),
    )


@pytest.fixture
def tools(pkce_settings):
    return sf_login_module.register(MCPServer("test"), pkce_settings)


def _write_cache(settings: Settings, refresh_token: str = "refresh-1") -> None:
    with open(settings.pkce_token_cache_path, "w") as f:
        json.dump({"refresh_token": refresh_token, "instance_url": INSTANCE_URL}, f)


async def test_already_logged_in_short_circuits_without_interactive_login(tools, pkce_settings, monkeypatch):
    _write_cache(pkce_settings)

    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("perform_interactive_login should not have been called")

    monkeypatch.setattr(sf_login_module, "perform_interactive_login", _should_not_be_called)

    async with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "tok", "instance_url": INSTANCE_URL})
        )
        result = await tools["sf_login"]()

    assert result == {"already_logged_in": True, "instance_url": INSTANCE_URL}


async def test_missing_cache_runs_interactive_login(tools, monkeypatch):
    async def _fake_interactive_login(settings, *, on_status=None):
        if on_status:
            await on_status("Opening your browser...")
        return {"instance_url": INSTANCE_URL, "cache_path": settings.pkce_token_cache_path}

    monkeypatch.setattr(sf_login_module, "perform_interactive_login", _fake_interactive_login)

    result = await tools["sf_login"]()

    assert result["already_logged_in"] is False
    assert result["instance_url"] == INSTANCE_URL


async def test_interactive_login_reports_progress_via_context(tools, monkeypatch):
    async def _fake_interactive_login(settings, *, on_status=None):
        if on_status:
            await on_status("Waiting for you to complete login...")
        return {"instance_url": INSTANCE_URL, "cache_path": settings.pkce_token_cache_path}

    monkeypatch.setattr(sf_login_module, "perform_interactive_login", _fake_interactive_login)
    ctx = FakeContext()

    await tools["sf_login"](ctx=ctx)

    assert any("Waiting for you to complete login" in msg for _, _, msg in ctx.progress_calls)


async def test_force_true_always_runs_interactive_login_even_with_valid_cache(
    tools, pkce_settings, monkeypatch
):
    _write_cache(pkce_settings)
    calls = []

    async def _fake_interactive_login(settings, *, on_status=None):
        calls.append(settings)
        return {"instance_url": "https://forced-login.my.salesforce.com", "cache_path": "irrelevant"}

    monkeypatch.setattr(sf_login_module, "perform_interactive_login", _fake_interactive_login)

    async with respx.mock(assert_all_called=False) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "tok", "instance_url": INSTANCE_URL})
        )
        result = await tools["sf_login"](force=True)

    assert len(calls) == 1
    assert result["already_logged_in"] is False
    assert result["instance_url"] == "https://forced-login.my.salesforce.com"


async def test_sf_login_registered_only_for_pkce_auth_flow():
    pkce_settings = Settings(login_url=LOGIN_URL, client_id="id", auth_flow="pkce")
    cc_settings = Settings(
        login_url=LOGIN_URL, client_id="id", client_secret="secret", auth_flow="client_credentials"
    )

    pkce_mcp, pkce_client, pkce_pubsub = build_server(pkce_settings)
    cc_mcp, cc_client, cc_pubsub = build_server(cc_settings)

    pkce_tool_names = {t.name for t in await pkce_mcp.list_tools()}
    cc_tool_names = {t.name for t in await cc_mcp.list_tools()}

    assert "sf_login" in pkce_tool_names
    assert "sf_login" not in cc_tool_names

    await pkce_client.aclose()
    await pkce_pubsub.aclose()
    await cc_client.aclose()
    await cc_pubsub.aclose()
