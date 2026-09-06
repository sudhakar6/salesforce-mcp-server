from __future__ import annotations

import asyncio
import logging

from mcp.server.mcpserver import MCPServer

from . import prompts as prompts_module
from . import resources as resources_module
from .config import Settings
from .http_auth import BearerAuthMiddleware
from .pubsub_client import PubSubClient
from .salesforce_client import SalesforceClient
from .tools import bulk, composite, custom_api, describe, ops, org_health, query, records, subscribe

logger = logging.getLogger("salesforce_mcp")

SERVER_INSTRUCTIONS = (
    "Tools and resources for interacting with a Salesforce org via its REST, "
    "Bulk API 2.0, and Composite APIs (SOQL query, SOSL search, record CRUD "
    "and upsert, bulk load, object describe/discovery, API usage, org health), "
    "plus a pass-through for custom Apex REST endpoints the org exposes, and "
    "ready-made prompts for common tasks (summarizing an Account, drafting a "
    "follow-up email, checking data hygiene), and a bounded platform-event/CDC "
    "replay tool. Broad queries/searches and deletes ask for confirmation via "
    "MCP Elicitation first (disable with SF_ELICITATION_ENABLED=false). This "
    "is an independent, open-source implementation of the Model Context "
    "Protocol spec against Salesforce's public APIs — it is not a Salesforce "
    "product and is not affiliated with or endorsed by Salesforce."
)


def build_server(settings: Settings) -> tuple[MCPServer, SalesforceClient, PubSubClient]:
    client = SalesforceClient(settings)
    pubsub_client = PubSubClient(client, settings.pubsub_host, settings.pubsub_port)
    mcp = MCPServer("salesforce-mcp-server", instructions=SERVER_INSTRUCTIONS)

    def get_client() -> SalesforceClient:
        return client

    def get_pubsub_client() -> PubSubClient:
        return pubsub_client

    for module in (describe, composite, ops, custom_api, org_health):
        module.register(mcp, get_client)
    query.register(mcp, get_client, elicitation_enabled=settings.elicitation_enabled)
    records.register(mcp, get_client, elicitation_enabled=settings.elicitation_enabled)
    bulk.register(mcp, get_client, elicitation_enabled=settings.elicitation_enabled)
    subscribe.register(mcp, get_client, get_pubsub_client)
    resources_module.register(mcp, get_client)
    prompts_module.register(mcp, get_client)

    return mcp, client, pubsub_client


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    mcp, client, pubsub_client = build_server(settings)

    if settings.transport == "http":
        asyncio.run(_run_http(mcp, client, pubsub_client, settings))
    else:
        asyncio.run(_run_stdio(mcp, client, pubsub_client))


async def _run_stdio(mcp: MCPServer, client: SalesforceClient, pubsub_client: PubSubClient) -> None:
    try:
        await mcp.run_stdio_async()
    finally:
        await client.aclose()
        await pubsub_client.aclose()


async def _run_http(
    mcp: MCPServer, client: SalesforceClient, pubsub_client: PubSubClient, settings: Settings
) -> None:
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
        await pubsub_client.aclose()


if __name__ == "__main__":
    main()
