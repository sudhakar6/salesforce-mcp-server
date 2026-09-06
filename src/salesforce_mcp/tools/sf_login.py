from __future__ import annotations

from collections.abc import Callable

import httpx
from mcp.server.mcpserver import Context, MCPServer

from ..auth.errors import SalesforceAuthError
from ..auth.pkce import PkceRefreshAuth
from ..config import Settings
from ..errors import as_tool_error
from ..login import perform_interactive_login


def register(mcp: MCPServer, settings: Settings) -> dict[str, Callable]:
    """Only call this when settings.auth_flow == "pkce" — sf_login is
    meaningless under Client Credentials Flow, since there's no concept of
    "log in" there at all (server.py checks this before calling register)."""

    @mcp.tool()
    @as_tool_error
    async def sf_login(force: bool = False, ctx: Context | None = None) -> dict:
        """Log in to Salesforce interactively (the "Login with Salesforce"
        PKCE flow) if not already logged in.

        Call this when another tool fails saying no cached PKCE login was
        found, or whenever you want to (re-)authenticate as a different
        Salesforce user. If a cached login already works, does nothing and
        reports that — pass force=True to log in again anyway. Otherwise
        opens your browser and walks through the login; progress is
        reported while it waits for you to finish in the browser (up to
        two minutes).
        """
        if not force:
            try:
                async with httpx.AsyncClient() as http:
                    _, instance_url = await PkceRefreshAuth(settings).get_access_token(http)
                return {"already_logged_in": True, "instance_url": instance_url}
            except SalesforceAuthError:
                pass  # no valid cached login yet — fall through to the interactive flow

        async def on_status(message: str) -> None:
            if ctx is not None:
                await ctx.report_progress(0, None, message)

        result = await perform_interactive_login(settings, on_status=on_status)
        return {"already_logged_in": False, **result}

    return {"sf_login": sf_login}
