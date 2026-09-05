from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.composite import register
from tests.conftest import DATA_BASE


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


async def test_sf_composite_forwards_requests_and_default_all_or_none(tools):
    sub_requests = [
        {
            "method": "POST",
            "url": "/services/data/v61.0/sobjects/Account",
            "referenceId": "NewAccount",
            "body": {"Name": "Acme"},
        }
    ]

    async with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{DATA_BASE}/composite").mock(
            return_value=httpx.Response(200, json={"compositeResponse": [{"httpStatusCode": 201}]})
        )
        result = await tools["sf_composite"](requests=sub_requests)

    sent_body = route.calls.last.request.content
    import json

    payload = json.loads(sent_body)
    assert payload["allOrNone"] is True
    assert payload["compositeRequest"] == sub_requests
    assert result["compositeResponse"][0]["httpStatusCode"] == 201


async def test_sf_composite_rejects_empty_requests(tools):
    with pytest.raises(ToolError, match="must not be empty"):
        await tools["sf_composite"](requests=[])
