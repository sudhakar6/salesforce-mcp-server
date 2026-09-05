from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.custom_api import register
from tests.conftest import INSTANCE_URL

APEX_REST_BASE = f"{INSTANCE_URL}/services/apexrest"


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


async def test_sf_call_apex_rest_get(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{APEX_REST_BASE}/MyApi/v1/accounts/001A").mock(
            return_value=httpx.Response(200, json={"id": "001A", "name": "Acme"})
        )
        result = await tools["sf_call_apex_rest"](method="get", path="/MyApi/v1/accounts/001A")

    assert result == {"id": "001A", "name": "Acme"}


async def test_sf_call_apex_rest_post_with_body(tools):
    async with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{APEX_REST_BASE}/MyApi/v1/accounts").mock(
            return_value=httpx.Response(201, json={"id": "001B"})
        )
        result = await tools["sf_call_apex_rest"](
            method="POST", path="/MyApi/v1/accounts", body={"name": "Globex"}
        )

    import json

    assert json.loads(route.calls.last.request.content) == {"name": "Globex"}
    assert result == {"id": "001B"}


async def test_sf_call_apex_rest_no_content_response(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.delete(f"{APEX_REST_BASE}/MyApi/v1/accounts/001A").mock(return_value=httpx.Response(204))
        result = await tools["sf_call_apex_rest"](method="DELETE", path="/MyApi/v1/accounts/001A")

    assert result == {"status_code": 204}


async def test_sf_call_apex_rest_rejects_unsupported_method(tools):
    with pytest.raises(ToolError, match="Unsupported HTTP method"):
        await tools["sf_call_apex_rest"](method="TRACE", path="/MyApi/v1/accounts")


async def test_sf_call_apex_rest_rejects_path_without_leading_slash(tools):
    with pytest.raises(ToolError, match="must start with"):
        await tools["sf_call_apex_rest"](method="GET", path="MyApi/v1/accounts")


async def test_sf_call_apex_rest_surfaces_salesforce_error(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{APEX_REST_BASE}/MyApi/v1/missing").mock(
            return_value=httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "no such resource"}])
        )
        with pytest.raises(ToolError, match="NOT_FOUND"):
            await tools["sf_call_apex_rest"](method="GET", path="/MyApi/v1/missing")
