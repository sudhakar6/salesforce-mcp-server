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


_RAW_SOBJECTS = [
    {
        "name": "Account",
        "label": "Account",
        "custom": False,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": True,
        "urls": {"sobject": "/services/data/v61.0/sobjects/Account"},
    },
    {
        "name": "My_Custom_Object__c",
        "label": "My Custom Object",
        "custom": True,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": True,
        "urls": {"sobject": "/services/data/v61.0/sobjects/My_Custom_Object__c"},
    },
]


async def test_sf_list_objects_trims_fields_and_reports_counts(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects").mock(
            return_value=httpx.Response(200, json={"sobjects": _RAW_SOBJECTS})
        )
        result = await tools["sf_list_objects"]()

    assert result["total_in_org"] == 2
    assert result["matched"] == 2
    assert [o["name"] for o in result["objects"]] == ["Account", "My_Custom_Object__c"]
    assert "urls" not in result["objects"][0]


async def test_sf_list_objects_custom_only_filter(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects").mock(
            return_value=httpx.Response(200, json={"sobjects": _RAW_SOBJECTS})
        )
        result = await tools["sf_list_objects"](custom_only=True)

    assert result["total_in_org"] == 2
    assert result["matched"] == 1
    assert result["objects"][0]["name"] == "My_Custom_Object__c"


async def test_sf_list_objects_name_contains_filter(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects").mock(
            return_value=httpx.Response(200, json={"sobjects": _RAW_SOBJECTS})
        )
        result = await tools["sf_list_objects"](name_contains="custom")

    assert result["matched"] == 1
    assert result["objects"][0]["name"] == "My_Custom_Object__c"
