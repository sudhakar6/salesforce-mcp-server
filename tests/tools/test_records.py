from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.records import register
from tests.conftest import DATA_BASE, FakeContext


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client, elicitation_enabled=False)


@pytest.fixture
def elicited_tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client, elicitation_enabled=True)


async def test_sf_get_record_with_field_restriction(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(f"{DATA_BASE}/sobjects/Account/001A", params={"fields": "Name,Industry"}).mock(
            return_value=httpx.Response(200, json={"Id": "001A", "Name": "Acme"})
        )
        result = await tools["sf_get_record"](
            sobject="Account", record_id="001A", fields=["Name", "Industry"]
        )

    assert result == {"Id": "001A", "Name": "Acme"}


async def test_sf_create_record(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.post(f"{DATA_BASE}/sobjects/Account").mock(
            return_value=httpx.Response(201, json={"id": "001A", "success": True, "errors": []})
        )
        result = await tools["sf_create_record"](sobject="Account", fields={"Name": "Acme"})

    assert result["id"] == "001A"


async def test_sf_update_record(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.patch(f"{DATA_BASE}/sobjects/Account/001A").mock(return_value=httpx.Response(204))
        result = await tools["sf_update_record"](
            sobject="Account", record_id="001A", fields={"Name": "Acme Inc"}
        )

    assert result == {"id": "001A", "success": True}


async def test_sf_upsert_record_created(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.patch(f"{DATA_BASE}/sobjects/Account/External_Id__c/ext-1").mock(
            return_value=httpx.Response(201, json={"id": "001A", "success": True, "errors": []})
        )
        result = await tools["sf_upsert_record"](
            sobject="Account",
            external_id_field="External_Id__c",
            external_id_value="ext-1",
            fields={"Name": "Acme"},
        )

    assert result["created"] is True
    assert result["id"] == "001A"


async def test_sf_upsert_record_updated(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.patch(f"{DATA_BASE}/sobjects/Account/External_Id__c/ext-1").mock(return_value=httpx.Response(204))
        result = await tools["sf_upsert_record"](
            sobject="Account",
            external_id_field="External_Id__c",
            external_id_value="ext-1",
            fields={"Name": "Acme"},
        )

    assert result == {"external_id": "ext-1", "success": True, "created": False}


async def test_sf_delete_record(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.delete(f"{DATA_BASE}/sobjects/Account/001A").mock(return_value=httpx.Response(204))
        result = await tools["sf_delete_record"](sobject="Account", record_id="001A")

    assert result == {"id": "001A", "success": True}


async def test_sf_delete_record_not_found_raises_tool_error(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.delete(f"{DATA_BASE}/sobjects/Account/nope").mock(
            return_value=httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "not found"}])
        )
        with pytest.raises(ToolError, match="NOT_FOUND"):
            await tools["sf_delete_record"](sobject="Account", record_id="nope")


async def test_sf_delete_record_always_confirms_when_elicitation_enabled(elicited_tools):
    ctx = FakeContext(action="accept", proceed=True)
    async with respx.mock(assert_all_called=True) as router:
        router.delete(f"{DATA_BASE}/sobjects/Account/001A").mock(return_value=httpx.Response(204))
        result = await elicited_tools["sf_delete_record"](sobject="Account", record_id="001A", ctx=ctx)

    assert len(ctx.messages) == 1
    assert result == {"id": "001A", "success": True}


async def test_sf_delete_record_declined_makes_no_salesforce_call(elicited_tools):
    ctx = FakeContext(action="decline")
    async with respx.mock(assert_all_called=True):
        result = await elicited_tools["sf_delete_record"](sobject="Account", record_id="001A", ctx=ctx)

    assert result == {"executed": False, "reason": "Declined confirmation for a delete."}
