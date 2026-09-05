from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.bulk import register
from tests.conftest import DATA_BASE


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


async def test_sf_bulk_query_polls_until_complete_and_pages_results(tools):
    job_id = "750xx0000000001"
    async with respx.mock(assert_all_called=True) as router:
        router.post(f"{DATA_BASE}/jobs/query").mock(
            return_value=httpx.Response(200, json={"id": job_id, "state": "UploadComplete"})
        )
        router.get(f"{DATA_BASE}/jobs/query/{job_id}").mock(
            side_effect=[
                httpx.Response(200, json={"id": job_id, "state": "InProgress"}),
                httpx.Response(200, json={"id": job_id, "state": "JobComplete", "numberRecordsProcessed": 2}),
            ]
        )
        results_route = router.get(f"{DATA_BASE}/jobs/query/{job_id}/results").mock(
            side_effect=[
                httpx.Response(200, text="Id,Name\n001A,Acme\n", headers={"Sforce-Locator": "page-2"}),
                httpx.Response(200, text="Id,Name\n001B,Globex\n", headers={"Sforce-Locator": "null"}),
            ]
        )

        result = await tools["sf_bulk_query"](soql="SELECT Id, Name FROM Account")

    assert result["job_id"] == job_id
    assert result["record_count"] == 2
    assert [r["Id"] for r in result["records"]] == ["001A", "001B"]
    assert results_route.call_count == 2


async def test_sf_bulk_query_raises_on_failed_job(tools):
    job_id = "750xx0000000002"
    async with respx.mock(assert_all_called=True) as router:
        router.post(f"{DATA_BASE}/jobs/query").mock(
            return_value=httpx.Response(200, json={"id": job_id, "state": "UploadComplete"})
        )
        router.get(f"{DATA_BASE}/jobs/query/{job_id}").mock(
            return_value=httpx.Response(
                200, json={"id": job_id, "state": "Failed", "errorMessage": "bad SOQL"}
            )
        )
        with pytest.raises(ToolError, match="Failed"):
            await tools["sf_bulk_query"](soql="SELECT bogus")


async def test_sf_bulk_load_insert_reports_failures(tools):
    job_id = "750yy0000000001"
    async with respx.mock(assert_all_called=True) as router:
        router.post(f"{DATA_BASE}/jobs/ingest").mock(return_value=httpx.Response(200, json={"id": job_id}))
        router.put(f"{DATA_BASE}/jobs/ingest/{job_id}/batches").mock(return_value=httpx.Response(201))
        router.patch(f"{DATA_BASE}/jobs/ingest/{job_id}").mock(
            return_value=httpx.Response(200, json={"id": job_id, "state": "UploadComplete"})
        )
        router.get(f"{DATA_BASE}/jobs/ingest/{job_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": job_id,
                    "state": "JobComplete",
                    "numberRecordsProcessed": 2,
                    "numberRecordsFailed": 1,
                },
            )
        )
        router.get(f"{DATA_BASE}/jobs/ingest/{job_id}/failedResults").mock(
            return_value=httpx.Response(200, text="sf__Id,sf__Error,Name\n,REQUIRED_FIELD_MISSING,\n")
        )

        result = await tools["sf_bulk_load"](
            sobject="Account", operation="insert", records=[{"Name": "Acme"}, {"Name": ""}]
        )

    assert result["records_processed"] == 2
    assert result["records_failed"] == 1
    assert result["failures"][0]["sf__Error"] == "REQUIRED_FIELD_MISSING"


async def test_sf_bulk_load_rejects_upsert_without_external_id_field(tools):
    with pytest.raises(ToolError, match="external_id_field is required"):
        await tools["sf_bulk_load"](sobject="Account", operation="upsert", records=[{"Name": "Acme"}])


async def test_sf_bulk_load_rejects_unsupported_operation(tools):
    with pytest.raises(ToolError, match="Unsupported bulk operation"):
        await tools["sf_bulk_load"](sobject="Account", operation="frobnicate", records=[{"Name": "Acme"}])


async def test_sf_bulk_load_rejects_empty_records(tools):
    with pytest.raises(ToolError, match="must not be empty"):
        await tools["sf_bulk_load"](sobject="Account", operation="insert", records=[])
