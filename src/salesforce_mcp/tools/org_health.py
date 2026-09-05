from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient

ORGANIZATION_QUERY = (
    "SELECT Id, Name, OrganizationType, InstanceName, IsSandbox, "
    "TrialExpirationDate, NamespacePrefix FROM Organization"
)
USER_LICENSE_QUERY = "SELECT Id, Name, TotalLicenses, UsedLicenses, Status FROM UserLicense"
PERMISSION_SET_LICENSE_QUERY = (
    "SELECT Id, MasterLabel, DeveloperName, TotalLicenses, UsedLicenses, Status, ExpirationDate "
    "FROM PermissionSetLicense"
)
PACKAGE_LICENSE_QUERY = (
    "SELECT Id, NamespacePrefix, AllowedLicenses, UsedLicenses, ExpirationDate, Status FROM PackageLicense"
)


async def _query(client: SalesforceClient, soql: str) -> list[dict]:
    response = await client.request("GET", "/query", params={"q": soql})
    raise_for_salesforce_error(response)
    return response.json().get("records", [])


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_org_health() -> dict:
        """Report the org's overall health: what kind of org it is, current API/
        storage/async limits, and license seat usage (user licenses, permission
        set licenses, installed package licenses).

        A heavier, broader report than sf_api_usage (which only checks the
        daily API request limit) — use this for "what does this org have and
        how much of it is used", not for a quick mid-conversation limit check.
        """
        client = get_client()

        limits_response = await client.request("GET", "/limits")
        raise_for_salesforce_error(limits_response)

        organization_records = await _query(client, ORGANIZATION_QUERY)
        user_licenses = await _query(client, USER_LICENSE_QUERY)
        permission_set_licenses = await _query(client, PERMISSION_SET_LICENSE_QUERY)
        package_licenses = await _query(client, PACKAGE_LICENSE_QUERY)

        return {
            "organization": organization_records[0] if organization_records else {},
            "limits": limits_response.json(),
            "user_licenses": user_licenses,
            "permission_set_licenses": permission_set_licenses,
            "package_licenses": package_licenses,
        }

    return {"sf_org_health": sf_org_health}
