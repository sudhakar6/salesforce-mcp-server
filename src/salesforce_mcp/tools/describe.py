from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient

# These two functions are plain (undecorated) so resources.py can reuse them
# directly without going through the Tool-specific error translation.

# Salesforce's raw global describe returns ~25 fields per object (including a
# nested `urls` block) - for a Developer Edition org's 800+ standard objects,
# that's large enough to exhaust a model's context on its own (found via
# real testing, not a hypothetical concern). Trimmed to what's actually
# useful for "what objects exist and what can I do with them."
_OBJECT_SUMMARY_FIELDS = ("name", "label", "custom", "queryable", "createable", "updateable", "deletable")


async def describe_object(client: SalesforceClient, sobject: str) -> dict:
    response = await client.request("GET", f"/sobjects/{sobject}/describe")
    raise_for_salesforce_error(response)
    return response.json()


async def list_objects(
    client: SalesforceClient,
    name_contains: str | None = None,
    custom_only: bool = False,
) -> dict:
    response = await client.request("GET", "/sobjects")
    raise_for_salesforce_error(response)
    all_objects = response.json().get("sobjects", [])

    summaries = [{field: obj.get(field) for field in _OBJECT_SUMMARY_FIELDS} for obj in all_objects]

    if name_contains:
        needle = name_contains.lower()
        summaries = [
            o
            for o in summaries
            if needle in (o["name"] or "").lower() or needle in (o["label"] or "").lower()
        ]
    if custom_only:
        summaries = [o for o in summaries if o["custom"]]

    return {"total_in_org": len(all_objects), "matched": len(summaries), "objects": summaries}


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_describe_object(sobject: str) -> dict:
        """Return field metadata (names, types, picklist values, etc.) for one object."""
        return await describe_object(get_client(), sobject)

    @mcp.tool()
    @as_tool_error
    async def sf_list_objects(name_contains: str | None = None, custom_only: bool = False) -> dict:
        """List objects available in the org (global describe), for discoverability.

        A Developer Edition org alone has 800+ standard objects, so the
        result is trimmed to name/label/custom/queryable/createable/
        updateable/deletable per object rather than Salesforce's full raw
        payload. Narrow further with `name_contains` (matches name or label,
        case-insensitive) or `custom_only=True` if you don't need the full
        list.
        """
        return await list_objects(get_client(), name_contains=name_contains, custom_only=custom_only)

    return {"sf_describe_object": sf_describe_object, "sf_list_objects": sf_list_objects}
