from __future__ import annotations

import pytest

from salesforce_mcp.config import Settings
from salesforce_mcp.salesforce_client import SalesforceClient

LOGIN_URL = "https://example.my.salesforce.com"
INSTANCE_URL = "https://inst.my.salesforce.com"
API_VERSION = "v61.0"
DATA_BASE = f"{INSTANCE_URL}/services/data/{API_VERSION}"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        client_secret="test-client-secret",
        api_version=API_VERSION,
    )


@pytest.fixture
async def authed_client(settings: Settings):
    """A SalesforceClient pre-seeded with a token, so tests don't need to mock
    the OAuth handshake unless they're specifically testing auth behavior."""
    client = SalesforceClient(settings)
    client._access_token = "cached-token"  # noqa: SLF001 - test seam
    client._instance_url = INSTANCE_URL  # noqa: SLF001 - test seam
    yield client
    await client.aclose()
