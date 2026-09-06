from __future__ import annotations

from salesforce_mcp.auth import build_auth
from salesforce_mcp.auth.client_credentials import ClientCredentialsAuth
from salesforce_mcp.auth.pkce import PkceRefreshAuth
from salesforce_mcp.config import Settings
from tests.conftest import LOGIN_URL


def test_builds_pkce_auth_by_default():
    settings = Settings(login_url=LOGIN_URL, client_id="id")
    assert isinstance(build_auth(settings), PkceRefreshAuth)


def test_builds_client_credentials_auth_when_explicitly_configured():
    settings = Settings(
        login_url=LOGIN_URL, client_id="id", client_secret="secret", auth_flow="client_credentials"
    )
    assert isinstance(build_auth(settings), ClientCredentialsAuth)
