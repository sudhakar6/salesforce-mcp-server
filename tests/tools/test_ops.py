from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer

from salesforce_mcp.tools.ops import register
from tests.conftest import DATA_BASE


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


async def test_sf_api_usage_reads_cached_limit_header(tools, authed_client):
    authed_client._last_limit_info = "api-usage=42/15000"  # noqa: SLF001 - test seam

    async with respx.mock(assert_all_called=False):
        result = await tools["sf_api_usage"]()

    assert result == {"used": 42, "limit": 15000}


async def test_sf_api_usage_falls_back_to_limits_endpoint(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/limits").mock(
            return_value=httpx.Response(200, json={"DailyApiRequests": {"Max": 15000, "Remaining": 14900}})
        )
        result = await tools["sf_api_usage"]()

    assert result == {"used": 100, "limit": 15000}
