from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.tools.org_health import register
from tests.conftest import DATA_BASE

QUERY_URL = f"{DATA_BASE}/query"
LIMITS_URL = f"{DATA_BASE}/limits"


@pytest.fixture
def tools(authed_client):
    return register(MCPServer("test"), lambda: authed_client)


def _query_response(records: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"totalSize": len(records), "done": True, "records": records})


async def test_sf_org_health_assembles_all_sections(tools):
    async with respx.mock(assert_all_called=True) as router:
        router.get(LIMITS_URL).mock(
            return_value=httpx.Response(200, json={"DailyApiRequests": {"Max": 15000, "Remaining": 14900}})
        )
        # org_health.py queries in a fixed order: Organization, UserLicense,
        # PermissionSetLicense, PackageLicense — side_effect list matches that order.
        router.get(QUERY_URL).mock(
            side_effect=[
                _query_response([{"Id": "00D1", "Name": "Acme Org", "IsSandbox": False}]),
                _query_response([{"Name": "Salesforce", "TotalLicenses": 10, "UsedLicenses": 7}]),
                _query_response([{"MasterLabel": "Sales Cloud Add-On", "UsedLicenses": 2}]),
                _query_response([]),
            ]
        )

        result = await tools["sf_org_health"]()

    assert result["organization"] == {"Id": "00D1", "Name": "Acme Org", "IsSandbox": False}
    assert result["limits"]["DailyApiRequests"]["Max"] == 15000
    assert result["user_licenses"][0]["Name"] == "Salesforce"
    assert result["permission_set_licenses"][0]["MasterLabel"] == "Sales Cloud Add-On"
    assert result["package_licenses"] == []


async def test_sf_org_health_surfaces_salesforce_error(tools, monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async with respx.mock(assert_all_called=True) as router:
        router.get(LIMITS_URL).mock(
            return_value=httpx.Response(
                403, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "no calls left"}]
            )
        )
        with pytest.raises(ToolError, match="REQUEST_LIMIT_EXCEEDED"):
            await tools["sf_org_health"]()
