from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from .errors import as_resource_error
from .salesforce_client import SalesforceClient
from .tools.describe import describe_object, list_objects


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> None:
    """Register describe/discovery data as MCP Resources, not just Tools.

    Backed by the same tools/describe.py functions as sf_list_objects and
    sf_describe_object — the data is reachable either as an explicit tool call
    or as a resource a client can pull into context implicitly. Deliberately
    two protocol surfaces over one implementation, not a duplicate one.
    """

    @mcp.resource(
        "salesforce://objects",
        name="Salesforce objects",
        description="Global describe: every object available in the org.",
        mime_type="application/json",
    )
    @as_resource_error
    async def objects_resource() -> dict:
        return await list_objects(get_client())

    @mcp.resource(
        "salesforce://schema/{sobject}",
        name="Salesforce object schema",
        description="Field metadata (names, types, picklist values) for one object, by API name.",
        mime_type="application/json",
    )
    @as_resource_error
    async def schema_resource(sobject: str) -> dict:
        return await describe_object(get_client(), sobject)
