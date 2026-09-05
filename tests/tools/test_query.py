from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.query import register
from tests.conftest import DATA_BASE


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


async def test_sf_query_follows_pagination(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/query", params={"q": "SELECT Id FROM Account"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "totalSize": 2,
                    "done": False,
                    "records": [{"Id": "001A"}],
                    "nextRecordsUrl": "/services/data/v61.0/query/01g-next",
                },
            )
        )
        router.get(f"{DATA_BASE}/query/01g-next").mock(
            return_value=httpx.Response(
                200, json={"totalSize": 2, "done": True, "records": [{"Id": "001B"}]}
            )
        )

        result = await tools["sf_query"](soql="SELECT Id FROM Account")

    assert result["total_size"] == 2
    assert [r["Id"] for r in result["records"]] == ["001A", "001B"]


async def test_sf_query_raises_tool_error_on_malformed_soql(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/query").mock(
            return_value=httpx.Response(
                400, json=[{"errorCode": "MALFORMED_QUERY", "message": "unexpected token"}]
            )
        )
        with pytest.raises(ToolError, match="MALFORMED_QUERY"):
            await tools["sf_query"](soql="SELEKT Id FROM Account")


async def test_sf_search_returns_raw_response(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/search").mock(
            return_value=httpx.Response(200, json={"searchRecords": [{"Id": "001A"}]})
        )
        result = await tools["sf_search"](sosl="FIND {Acme} IN ALL FIELDS RETURNING Account(Name)")

    assert result["searchRecords"] == [{"Id": "001A"}]
