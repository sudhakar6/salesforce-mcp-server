from __future__ import annotations

import pytest
from mcp.server.mcpserver import AcceptedElicitation, CancelledElicitation, DeclinedElicitation

from salesforce_mcp.config import Settings
from salesforce_mcp.salesforce_client import SalesforceClient

LOGIN_URL = "https://example.my.salesforce.com"
INSTANCE_URL = "https://inst.my.salesforce.com"
API_VERSION = "v61.0"
DATA_BASE = f"{INSTANCE_URL}/services/data/{API_VERSION}"


@pytest.fixture
def settings() -> Settings:
    """Pins auth_flow explicitly to client_credentials — this fixture backs
    every test exercising real Client Credentials Flow behavior, so it must
    not silently follow whatever Settings' own default happens to be."""
    return Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        client_secret="test-client-secret",
        api_version=API_VERSION,
        auth_flow="client_credentials",
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


class FakeContext:
    """Stands in for mcp.server.mcpserver.Context — implements only what
    tests actually need: elicit() (elicitation tests) and report_progress()
    (sf_login's progress-while-waiting). Records every elicit() message and
    every report_progress() call; elicit() returns a canned ElicitationResult
    matching `action` (and, for "accept", `proceed`)."""

    def __init__(self, action: str = "accept", proceed: bool = True):
        self.action = action
        self.proceed = proceed
        self.messages: list[str] = []
        self.progress_calls: list[tuple[float, float | None, str | None]] = []

    async def elicit(self, message: str, schema):
        self.messages.append(message)
        if self.action == "accept":
            return AcceptedElicitation(data=schema(proceed=self.proceed))
        if self.action == "decline":
            return DeclinedElicitation()
        return CancelledElicitation()

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None):
        self.progress_calls.append((progress, total, message))
