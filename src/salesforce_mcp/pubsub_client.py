from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import fastavro
import grpc

from .pubsub import pubsub_api_pb2 as pb2
from .pubsub import pubsub_api_pb2_grpc as pb2_grpc
from .salesforce_client import SalesforceClient


@dataclass
class PubSubEvent:
    replay_id: bytes
    created_date: dt.datetime | None
    payload: dict


class PubSubClient:
    """Thin wrapper around Salesforce's Pub/Sub API (gRPC) for platform
    events and Change Data Capture.

    A different transport than SalesforceClient's REST calls: auth is
    per-call gRPC metadata (accesstoken/instanceurl/tenantid — see
    PubSubStub's own docstring in pubsub_api_pb2_grpc.py), not a Bearer
    header, and payloads are Avro-encoded, not JSON. `stub` is injectable so
    tests can substitute a fake one instead of opening a real TLS/gRPC
    connection — the same DI shape `get_client` uses everywhere else in this
    codebase.

    Deliberately simple: this exists to serve one bounded tool call
    (sf_subscribe_platform_event), not to be a general-purpose streaming
    client — it sends a single FetchRequest and yields whatever comes back
    until the caller stops iterating. No dynamic flow-control top-ups, no
    auto-reconnect on a dropped stream.
    """

    def __init__(
        self,
        sf_client: SalesforceClient,
        host: str,
        port: int,
        stub: pb2_grpc.PubSubStub | None = None,
    ):
        self._sf_client = sf_client
        self._host = host
        self._port = port
        self._schema_cache: dict[str, object] = {}
        self._channel = None
        self._stub = stub

    async def _ensure_stub(self) -> pb2_grpc.PubSubStub:
        """Lazily create the gRPC channel/stub on first actual use.

        Deliberately NOT done in __init__: this client is constructed once
        in build_server(), which runs *before* main()'s asyncio.run() starts
        the event loop that will actually drive the server. grpc.aio.Channel
        binds to whatever loop is current at creation time — creating it
        eagerly there attaches it to a throwaway loop, and the first real
        RPC then fails with "Future attached to a different loop" (a plain
        RuntimeError, confirmed by reproducing it directly). Creating it
        lazily, on first await from inside the real running loop, avoids
        that entirely. Injected `stub` (tests) bypasses this altogether.
        """
        if self._stub is None:
            channel = grpc.aio.secure_channel(f"{self._host}:{self._port}", grpc.ssl_channel_credentials())
            self._channel = channel
            self._stub = pb2_grpc.PubSubStub(channel)
        return self._stub

    async def aclose(self) -> None:
        if self._channel is not None:
            await self._channel.close()

    async def _metadata(self) -> tuple[tuple[str, str], ...]:
        access_token, instance_url, org_id = await self._sf_client.get_pubsub_auth()
        return (
            ("accesstoken", access_token),
            ("instanceurl", instance_url),
            ("tenantid", org_id),
        )

    async def _get_schema(self, schema_id: str):
        cached = self._schema_cache.get(schema_id)
        if cached is not None:
            return cached
        stub = await self._ensure_stub()
        metadata = await self._metadata()
        schema_info = await stub.GetSchema(pb2.SchemaRequest(schema_id=schema_id), metadata=metadata)
        schema = fastavro.parse_schema(json.loads(schema_info.schema_json))
        self._schema_cache[schema_id] = schema
        return schema

    async def subscribe(
        self,
        topic: str,
        replay_preset: str,
        *,
        replay_id: bytes = b"",
        num_requested: int,
    ) -> AsyncIterator[PubSubEvent]:
        """Yield decoded events from `topic` until the caller stops
        iterating. The caller (tools/subscribe.py) owns all stopping logic
        (max events, end_time, timeout) and must close this generator
        (`await gen.aclose()`) when done — that's what cancels the
        underlying gRPC call.
        """
        preset = pb2.ReplayPreset.Value(replay_preset)
        stub = await self._ensure_stub()
        metadata = await self._metadata()

        async def request_iterator():
            yield pb2.FetchRequest(
                topic_name=topic,
                replay_preset=preset,
                replay_id=replay_id,
                num_requested=num_requested,
            )
            # Keep the request (write) side of the stream open instead of
            # half-closing it right after the first message. Confirmed by
            # direct testing against a real org: half-closing immediately
            # after one FetchRequest yielded zero events AND zero keepalives
            # even when GetTopic confirmed can_subscribe=True and a valid
            # schema_id — Salesforce appears to stop delivering once the
            # client signals it's done sending. The caller cancels the call
            # (see `finally` below / tools/subscribe.py) when it's collected
            # enough; there's nothing more this side needs to send meanwhile.
            await asyncio.Event().wait()

        call = stub.Subscribe(request_iterator(), metadata=metadata)
        try:
            async for response in call:
                for consumer_event in response.events:
                    schema = await self._get_schema(consumer_event.event.schema_id)
                    payload = fastavro.schemaless_reader(io.BytesIO(consumer_event.event.payload), schema)
                    yield PubSubEvent(
                        replay_id=consumer_event.replay_id,
                        created_date=_extract_created_date(payload),
                        payload=payload,
                    )
        finally:
            call.cancel()


def _extract_created_date(payload: dict) -> dt.datetime | None:
    """Standard platform events carry a `CreatedDate` field; Change Data
    Capture events carry the equivalent under `ChangeEventHeader.commitTimestamp`
    (epoch milliseconds) instead. Returns None if neither is present or
    parseable — callers must treat that as "unknown", not "before start_time".
    """
    created = payload.get("CreatedDate")
    if created is None:
        header = payload.get("ChangeEventHeader")
        if isinstance(header, dict):
            created = header.get("commitTimestamp")

    if isinstance(created, dt.datetime):
        return created if created.tzinfo else created.replace(tzinfo=dt.UTC)
    if isinstance(created, int | float):
        return dt.datetime.fromtimestamp(created / 1000, tz=dt.UTC)
    if isinstance(created, str):
        try:
            return dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
