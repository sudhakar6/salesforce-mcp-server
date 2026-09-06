"""Standalone Pub/Sub API diagnostic — bypasses sf_subscribe_platform_event's
time-filtering logic entirely, so we can see exactly what Salesforce hands
back for a topic: does GetTopic confirm subscribe access, and does a raw
EARLIEST Subscribe deliver any events at all.

Reads the same .env the server does (via Settings.from_env()) — run it from
the project root with the venv active:

    python scripts/diagnose_pubsub.py mcp_server_test__e

Pass a bare platform-event API name (gets /event/ prefixed) or a full topic
path (e.g. /data/AccountChangeEvent).
"""

from __future__ import annotations

import asyncio
import io
import json
import sys

import fastavro
import grpc

sys.path.insert(0, "src")

from salesforce_mcp.config import Settings  # noqa: E402
from salesforce_mcp.pubsub import pubsub_api_pb2 as pb2  # noqa: E402
from salesforce_mcp.pubsub import pubsub_api_pb2_grpc as pb2_grpc  # noqa: E402
from salesforce_mcp.salesforce_client import SalesforceClient  # noqa: E402

LISTEN_SECONDS = 15
NUM_REQUESTED = 50


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/diagnose_pubsub.py <api_name_or_topic>")
        sys.exit(1)

    raw = sys.argv[1]
    topic = raw if raw.startswith("/") else f"/event/{raw}"

    settings = Settings.from_env()
    sf_client = SalesforceClient(settings)

    access_token, instance_url, org_id = await sf_client.get_pubsub_auth()
    print(f"Authenticated OK. instance_url={instance_url} org_id={org_id}")
    metadata = (
        ("accesstoken", access_token),
        ("instanceurl", instance_url),
        ("tenantid", org_id),
    )

    channel = grpc.aio.secure_channel(f"{settings.pubsub_host}:{settings.pubsub_port}", grpc.ssl_channel_credentials())
    stub = pb2_grpc.PubSubStub(channel)

    print(f"\n--- GetTopic({topic!r}) ---")
    try:
        topic_info = await stub.GetTopic(pb2.TopicRequest(topic_name=topic), metadata=metadata)
        print(f"  tenant_guid:    {topic_info.tenant_guid}")
        print(f"  can_publish:    {topic_info.can_publish}")
        print(f"  can_subscribe:  {topic_info.can_subscribe}")
        print(f"  schema_id:      {topic_info.schema_id}")
    except grpc.aio.AioRpcError as exc:
        print(f"  GetTopic FAILED: {exc.code()} — {exc.details()}")

    print(f"\n--- Subscribe({topic!r}, EARLIEST, num_requested={NUM_REQUESTED}) for {LISTEN_SECONDS}s ---")

    async def request_iterator():
        yield pb2.FetchRequest(
            topic_name=topic,
            replay_preset=pb2.ReplayPreset.EARLIEST,
            num_requested=NUM_REQUESTED,
        )
        # Keep the write side open rather than half-closing right after the
        # first message — see pubsub_client.py's subscribe() for why.
        await asyncio.Event().wait()

    call = stub.Subscribe(request_iterator(), metadata=metadata)
    event_count = 0
    schema_cache: dict[str, object] = {}
    try:
        async with asyncio.timeout(LISTEN_SECONDS):
            async for response in call:
                if not response.events:
                    print(f"  (keepalive, latest_replay_id={response.latest_replay_id!r})")
                    continue
                for consumer_event in response.events:
                    event_count += 1
                    schema_id = consumer_event.event.schema_id
                    if schema_id not in schema_cache:
                        schema_info = await stub.GetSchema(
                            pb2.SchemaRequest(schema_id=schema_id), metadata=metadata
                        )
                        schema_cache[schema_id] = fastavro.parse_schema(json.loads(schema_info.schema_json))
                    payload = fastavro.schemaless_reader(
                        io.BytesIO(consumer_event.event.payload), schema_cache[schema_id]
                    )
                    print(f"  event #{event_count}: replay_id={consumer_event.replay_id!r} payload={payload}")
    except TimeoutError:
        print(f"  (stopped after {LISTEN_SECONDS}s)")
    except grpc.aio.AioRpcError as exc:
        print(f"  Subscribe FAILED: {exc.code()} — {exc.details()}")
    finally:
        call.cancel()

    print(f"\nTotal events received: {event_count}")

    try:
        code = await call.code()
        details = await call.details()
        print(f"Final call status: {code} — {details!r}")
    except Exception as exc:  # noqa: BLE001 - diagnostic best-effort
        print(f"(could not read final call status: {exc})")

    await channel.close()
    await sf_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
