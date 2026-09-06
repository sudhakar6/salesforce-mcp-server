from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.shared.exceptions import MCPError

from salesforce_mcp.auth.errors import SalesforceAuthError
from salesforce_mcp.config import Settings
from salesforce_mcp.errors import as_prompt_error, as_resource_error, as_tool_error
from salesforce_mcp.salesforce_client import SalesforceClient
from salesforce_mcp.tools.describe import register
from tests.conftest import LOGIN_URL


async def test_as_tool_error_surfaces_salesforce_auth_error_message():
    @as_tool_error
    async def fails():
        raise SalesforceAuthError("no cached PKCE login found")

    with pytest.raises(ToolError, match="no cached PKCE login found"):
        await fails()


async def test_as_resource_error_surfaces_salesforce_auth_error_message():
    @as_resource_error
    async def fails():
        raise SalesforceAuthError("no cached PKCE login found")

    with pytest.raises(ResourceError, match="no cached PKCE login found"):
        await fails()


async def test_as_prompt_error_surfaces_salesforce_auth_error_message():
    @as_prompt_error
    async def fails():
        raise SalesforceAuthError("no cached PKCE login found")

    with pytest.raises(MCPError, match="no cached PKCE login found"):
        await fails()


async def test_pkce_missing_cache_surfaces_cleanly_through_a_real_tool_call(tmp_path):
    """End-to-end regression for the exact scenario a live test turned up:
    SF_AUTH_FLOW=pkce with no cached login yet used to crash any tool call
    with a generic "Error executing tool" message instead of the clean,
    actionable one — because SalesforceAuthError wasn't in as_tool_error's
    except clause. sf_describe_object is an arbitrary stand-in; the bug was
    in shared code every tool goes through, not this one specifically."""
    settings = Settings(
        login_url=LOGIN_URL,
        client_id="test-client-id",
        auth_flow="pkce",
        pkce_token_cache_path=str(tmp_path / "missing.json"),
    )
    client = SalesforceClient(settings)
    tools = register(MCPServer("test"), lambda: client)

    with pytest.raises(ToolError, match="run `python -m salesforce_mcp.login`"):
        await tools["sf_describe_object"](sobject="Account")

    await client.aclose()
