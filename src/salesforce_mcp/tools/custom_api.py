from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient

SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_call_apex_rest(
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Call a custom Apex REST endpoint exposed by the org.

        For any org-specific capability beyond this server's built-in
        standard-API tools: an Apex class annotated `@RestResource(urlMapping=...)`
        with `@HttpGet`/`@HttpPost`/etc. methods. `path` is that class's URL
        mapping, e.g. "/MyApi/v1/accounts/001xx0000000001AAA" for a class
        registered with `@RestResource(urlMapping='/MyApi/v1/accounts/*')`.
        `method` must match whichever HTTP method the class handles.

        This is a thin, generic pass-through — it has no idea what any
        particular custom endpoint does, expects, or returns; that's between
        the caller and whatever the org's Apex class implements.
        """
        normalized_method = method.upper()
        if normalized_method not in SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported HTTP method {method!r}; expected one of {sorted(SUPPORTED_METHODS)}"
            )
        if not path.startswith("/"):
            raise ValueError("path must start with '/', e.g. '/MyApi/v1/accounts/001xx'")

        client = get_client()
        response = await client.request(
            normalized_method,
            f"/services/apexrest{path}",
            versioned=False,
            params=params,
            json=body,
        )
        raise_for_salesforce_error(response)

        if not response.content:
            return {"status_code": response.status_code}
        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "text": response.text}

    return {"sf_call_apex_rest": sf_call_apex_rest}
