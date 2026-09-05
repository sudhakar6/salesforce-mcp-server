from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_query(soql: str) -> dict:
        """Run a SOQL query and return matching records.

        Follows `nextRecordsUrl` automatically so the full result set is
        returned in one call, regardless of Salesforce's per-page row limit.
        """
        client = get_client()
        records: list[dict] = []
        response = await client.request("GET", "/query", params={"q": soql})
        raise_for_salesforce_error(response)
        body = response.json()
        records.extend(body.get("records", []))
        next_url = body.get("nextRecordsUrl")
        while next_url:
            response = await client.request("GET", next_url, versioned=False)
            raise_for_salesforce_error(response)
            body = response.json()
            records.extend(body.get("records", []))
            next_url = body.get("nextRecordsUrl")
        return {"total_size": body.get("totalSize", len(records)), "records": records}

    @mcp.tool()
    @as_tool_error
    async def sf_search(sosl: str) -> dict:
        """Run a raw SOSL search and return matching records grouped by object type.

        Example: FIND {Acme} IN ALL FIELDS RETURNING Account(Name), Contact(Name, Email)

        Complements sf_query: SOSL matches keywords across multiple object
        types and text fields at once, where SOQL needs an exact object and
        field match.
        """
        client = get_client()
        response = await client.request("GET", "/search", params={"q": sosl})
        raise_for_salesforce_error(response)
        return response.json()

    return {"sf_query": sf_query, "sf_search": sf_search}
