from __future__ import annotations

import asyncio
import logging

from mcp.server.mcpserver import MCPServer

from . import resources as resources_module
from .config import Settings
from .http_auth import BearerAuthMiddleware
from .salesforce_client import SalesforceClient
from .tools import bulk, composite, custom_api, describe, ops, query, records

logger = logging.getLogger("salesforce_mcp")

SERVER_INSTRUCTIONS = (
    "Tools and resources for interacting with a Salesforce org via its REST, "
    "Bulk API 2.0, and Composite APIs (SOQL query, SOSL search, record CRUD "
    "and upsert, bulk load, object describe/discovery, API usage), plus a "
    "pass-through for custom Apex REST endpoints the org exposes. This is an "
    "independent, open-source implementation of the Model Context Protocol "
    "spec against Salesforce's public APIs — it is not a Salesforce product "
    "and is not affiliated with or endorsed by Salesforce."
)


def build_server(settings: Settings) -> tuple[MCPServer, SalesforceClient]:
    client = SalesforceClient(settings)
    mcp = MCPServer("salesforce-mcp-server", instructions=SERVER_INSTRUCTIONS)

    def get_client() -> SalesforceClient:
        return client

    for module in (query, records, describe, bulk, composite, ops, custom_api):
        module.register(mcp, get_client)
    resources_module.register(mcp, get_client)

    return mcp, client


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    mcp, client = build_server(settings)

    if settings.transport == "http":
        asyncio.run(_run_http(mcp, client, settings))
    else:
        asyncio.run(_run_stdio(mcp, client))


async def _run_stdio(mcp: MCPServer, client: SalesforceClient) -> None:
    try:
        await mcp.run_stdio_async()
    finally:
        await client.aclose()


async def _run_http(mcp: MCPServer, client: SalesforceClient, settings: Settings) -> None:
    import uvicorn

    app = mcp.streamable_http_app(host=settings.host)
    assert settings.server_token is not None  # enforced in Settings.from_env
    app.add_middleware(BearerAuthMiddleware, token=settings.server_token)

    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
    server = uvicorn.Server(config)
    logger.info("Serving Streamable HTTP on %s:%s", settings.host, settings.port)
    try:
        await server.serve()
    finally:
        await client.aclose()


if __name__ == "__main__":
    main()
