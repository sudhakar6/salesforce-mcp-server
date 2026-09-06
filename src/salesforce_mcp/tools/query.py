from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import Context, MCPServer

from ..elicitation import confirm, soql_looks_unscoped, sosl_looks_unscoped
from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(
    mcp: MCPServer, get_client: Callable[[], SalesforceClient], elicitation_enabled: bool
) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_query(soql: str, ctx: Context | None = None) -> dict:
        """Run a SOQL query and return matching records.

        Follows `nextRecordsUrl` automatically so the full result set is
        returned in one call, regardless of Salesforce's per-page row limit.

        If `soql` has no WHERE clause and/or no LIMIT, asks for confirmation
        first via MCP Elicitation (it could return a very large number of
        rows) — disable with SF_ELICITATION_ENABLED=false.
        """
        if soql_looks_unscoped(soql):
            proceed = await confirm(
                ctx,
                f"This SOQL query has no WHERE clause and/or no LIMIT, and could "
                f"return a very large number of records:\n\n{soql}\n\nProceed?",
                enabled=elicitation_enabled,
            )
            if not proceed:
                return {"executed": False, "reason": "Declined confirmation for an unscoped query."}

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
    async def sf_search(sosl: str, ctx: Context | None = None) -> dict:
        """Run a raw SOSL search and return matching records grouped by object type.

        Example: FIND {Acme} IN ALL FIELDS RETURNING Account(Name), Contact(Name, Email)

        Complements sf_query: SOSL matches keywords across multiple object
        types and text fields at once, where SOQL needs an exact object and
        field match.

        If `sosl` has no RETURNING clause and/or no LIMIT, asks for
        confirmation first via MCP Elicitation (see sf_query for why) —
        disable with SF_ELICITATION_ENABLED=false.
        """
        if sosl_looks_unscoped(sosl):
            proceed = await confirm(
                ctx,
                f"This SOSL search has no RETURNING clause and/or no LIMIT, and "
                f"could return a very large number of records:\n\n{sosl}\n\nProceed?",
                enabled=elicitation_enabled,
            )
            if not proceed:
                return {"executed": False, "reason": "Declined confirmation for an unscoped search."}

        client = get_client()
        response = await client.request("GET", "/search", params={"q": sosl})
        raise_for_salesforce_error(response)
        return response.json()

    return {"sf_query": sf_query, "sf_search": sf_search}
