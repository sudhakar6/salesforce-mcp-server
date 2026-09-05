from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def _parse_limit_info(raw: str) -> dict[str, dict[str, int]]:
    """Parse a `Sforce-Limit-Info` header value, e.g. "api-usage=25/15000"."""
    parsed: dict[str, dict[str, int]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if "=" not in entry or "/" not in entry:
            continue
        key, value = entry.split("=", 1)
        used_str, _, limit_str = value.partition("/")
        try:
            parsed[key] = {"used": int(used_str), "limit": int(limit_str)}
        except ValueError:
            continue
    return parsed


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_api_usage() -> dict:
        """Report current Salesforce REST API usage against the org's daily limit.

        Reads the `Sforce-Limit-Info` header from the most recent API call when
        available (no extra request needed); falls back to a `/limits` call
        otherwise (e.g. right after server startup, before any other tool ran).
        """
        client = get_client()
        cached = client.last_limit_info
        if cached:
            usage = _parse_limit_info(cached).get("api-usage")
            if usage:
                return usage

        response = await client.request("GET", "/limits")
        raise_for_salesforce_error(response)
        daily = response.json().get("DailyApiRequests", {})
        max_requests = daily.get("Max", 0)
        remaining = daily.get("Remaining", max_requests)
        return {"used": max_requests - remaining, "limit": max_requests}

    return {"sf_api_usage": sf_api_usage}
