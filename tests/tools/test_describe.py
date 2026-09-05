from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer

from salesforce_mcp.tools.describe import register
from tests.conftest import DATA_BASE


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


async def test_sf_describe_object(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects/Account/describe").mock(
            return_value=httpx.Response(200, json={"name": "Account", "fields": [{"name": "Name"}]})
        )
        result = await tools["sf_describe_object"](sobject="Account")

    assert result["name"] == "Account"


async def test_sf_list_objects(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects").mock(
            return_value=httpx.Response(200, json={"sobjects": [{"name": "Account"}, {"name": "Contact"}]})
        )
        result = await tools["sf_list_objects"]()

    assert [o["name"] for o in result["sobjects"]] == ["Account", "Contact"]
