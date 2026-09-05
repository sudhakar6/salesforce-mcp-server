from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_composite(requests: list[dict], all_or_none: bool = True) -> dict:
        """Bundle multiple sub-requests into one atomic Salesforce API call.

        Each entry in `requests` is a Salesforce composite sub-request, e.g.:
        {"method": "POST", "url": "/services/data/v61.0/sobjects/Account",
         "referenceId": "NewAccount", "body": {"Name": "Acme"}}
        A later sub-request can reference an earlier one's result with
        "@{NewAccount.id}" inside its own body or url. With `all_or_none` true
        (the default), the whole batch rolls back if any sub-request fails.
        """
        if not requests:
            raise ValueError("requests must not be empty")
        client = get_client()
        response = await client.request(
            "POST",
            "/composite",
            json={"allOrNone": all_or_none, "compositeRequest": requests},
        )
        raise_for_salesforce_error(response)
        return response.json()

    return {"sf_composite": sf_composite}
