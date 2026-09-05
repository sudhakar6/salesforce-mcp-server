from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_get_record(sobject: str, record_id: str, fields: list[str] | None = None) -> dict:
        """Fetch a single record by ID. Pass `fields` to restrict which fields come back."""
        client = get_client()
        params = {"fields": ",".join(fields)} if fields else None
        response = await client.request("GET", f"/sobjects/{sobject}/{record_id}", params=params)
        raise_for_salesforce_error(response)
        return response.json()

    @mcp.tool()
    @as_tool_error
    async def sf_create_record(sobject: str, fields: dict) -> dict:
        """Create a new record of the given object type with the given field values."""
        client = get_client()
        response = await client.request("POST", f"/sobjects/{sobject}", json=fields)
        raise_for_salesforce_error(response)
        return response.json()

    @mcp.tool()
    @as_tool_error
    async def sf_update_record(sobject: str, record_id: str, fields: dict) -> dict:
        """Update an existing record's field values."""
        client = get_client()
        response = await client.request("PATCH", f"/sobjects/{sobject}/{record_id}", json=fields)
        raise_for_salesforce_error(response)
        return {"id": record_id, "success": True}

    @mcp.tool()
    @as_tool_error
    async def sf_upsert_record(
        sobject: str,
        external_id_field: str,
        external_id_value: str,
        fields: dict,
    ) -> dict:
        """Create or update a record identified by an external ID field.

        The standard idempotent create-or-update integration pattern: safe to
        call repeatedly with the same external ID without creating duplicates.
        """
        client = get_client()
        response = await client.request(
            "PATCH",
            f"/sobjects/{sobject}/{external_id_field}/{external_id_value}",
            json=fields,
        )
        raise_for_salesforce_error(response)
        if response.status_code == 201:
            return {**response.json(), "created": True}
        return {"external_id": external_id_value, "success": True, "created": False}

    @mcp.tool()
    @as_tool_error
    async def sf_delete_record(sobject: str, record_id: str) -> dict:
        """Delete a record by ID."""
        client = get_client()
        response = await client.request("DELETE", f"/sobjects/{sobject}/{record_id}")
        raise_for_salesforce_error(response)
        return {"id": record_id, "success": True}

    return {
        "sf_get_record": sf_get_record,
        "sf_create_record": sf_create_record,
        "sf_update_record": sf_update_record,
        "sf_upsert_record": sf_upsert_record,
        "sf_delete_record": sf_delete_record,
    }
