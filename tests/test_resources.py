from __future__ import annotations

import json

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from salesforce_mcp import resources
from tests.conftest import DATA_BASE


@pytest.fixture
def mcp(authed_client):
    server = MCPServer("test")
    resources.register(server, lambda: authed_client)
    return server


async def test_objects_resource_returns_global_describe(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects").mock(
            return_value=httpx.Response(
                200, json={"sobjects": [{"name": "Account", "label": "Account", "custom": False}]}
            )
        )
        contents = await mcp.read_resource("salesforce://objects")

    body = json.loads(contents[0].content)
    assert body["total_in_org"] == 1
    assert body["objects"][0]["name"] == "Account"


async def test_schema_resource_returns_object_describe(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects/Account/describe").mock(
            return_value=httpx.Response(200, json={"name": "Account", "fields": []})
        )
        contents = await mcp.read_resource("salesforce://schema/Account")

    body = json.loads(contents[0].content)
    assert body["name"] == "Account"


async def test_schema_resource_raises_not_found_for_unknown_object(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects/NoSuchObject__c/describe").mock(
            return_value=httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "not found"}])
        )
        with pytest.raises(ResourceNotFoundError):
            await mcp.read_resource("salesforce://schema/NoSuchObject__c")
