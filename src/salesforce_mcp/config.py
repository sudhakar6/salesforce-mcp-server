from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_API_VERSION = "v61.0"
DEFAULT_PORT = 8080
DEFAULT_PUBSUB_HOST = "api.pubsub.salesforce.com"
DEFAULT_PUBSUB_PORT = 7443


@dataclass(frozen=True)
class Settings:
    login_url: str
    client_id: str
    client_secret: str
    api_version: str = DEFAULT_API_VERSION
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    server_token: str | None = None
    pubsub_host: str = DEFAULT_PUBSUB_HOST
    pubsub_port: int = DEFAULT_PUBSUB_PORT
    elicitation_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        transport = os.environ.get("MCP_TRANSPORT", "stdio")
        server_token = os.environ.get("MCP_SERVER_TOKEN")
        if transport == "http" and not server_token:
            raise RuntimeError(
                "MCP_SERVER_TOKEN is required when MCP_TRANSPORT=http "
                "(it protects the publicly reachable endpoint)."
            )
        return cls(
            login_url=_require_env("SF_LOGIN_URL").rstrip("/"),
            client_id=_require_env("SF_CLIENT_ID"),
            client_secret=_require_env("SF_CLIENT_SECRET"),
            api_version=os.environ.get("SF_API_VERSION", DEFAULT_API_VERSION),
            transport=transport,
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", os.environ.get("MCP_PORT", str(DEFAULT_PORT)))),
            server_token=server_token,
            pubsub_host=os.environ.get("SF_PUBSUB_HOST", DEFAULT_PUBSUB_HOST),
            pubsub_port=int(os.environ.get("SF_PUBSUB_PORT", str(DEFAULT_PUBSUB_PORT))),
            elicitation_enabled=_parse_bool(os.environ.get("SF_ELICITATION_ENABLED"), default=True),
        )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
