from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient

# These two functions are plain (undecorated) so resources.py can reuse them
# directly without going through the Tool-specific error translation.


async def describe_object(client: SalesforceClient, sobject: str) -> dict:
    response = await client.request("GET", f"/sobjects/{sobject}/describe")
    raise_for_salesforce_error(response)
    return response.json()


async def list_objects(client: SalesforceClient) -> dict:
    response = await client.request("GET", "/sobjects")
    raise_for_salesforce_error(response)
    return response.json()


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_describe_object(sobject: str) -> dict:
        """Return field metadata (names, types, picklist values, etc.) for one object."""
        return await describe_object(get_client(), sobject)

    @mcp.tool()
    @as_tool_error
    async def sf_list_objects() -> dict:
        """List every object available in the org (global describe), for discoverability."""
        return await list_objects(get_client())

    return {"sf_describe_object": sf_describe_object, "sf_list_objects": sf_list_objects}
