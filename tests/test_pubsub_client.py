from __future__ import annotations

import asyncio
import datetime as dt
import io
import json

import fastavro
import pytest

from salesforce_mcp.pubsub import pubsub_api_pb2 as pb2
from salesforce_mcp.pubsub_client import PubSubClient

TEST_SCHEMA = {
    "type": "record",
    "name": "TestEvent",
    "fields": [
        {"name": "CreatedDate", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "Message__c", "type": "string"},
    ],
}
PARSED_SCHEMA = fastavro.parse_schema(TEST_SCHEMA)


def _encode(created_date: dt.datetime, message: str) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, PARSED_SCHEMA, {"CreatedDate": created_date, "Message__c": message})
    return buf.getvalue()


def _consumer_event(
    replay_id: bytes, schema_id: str, created_date: dt.datetime, message: str
) -> pb2.ConsumerEvent:
    return pb2.ConsumerEvent(
        event=pb2.ProducerEvent(schema_id=schema_id, payload=_encode(created_date, message)),
        replay_id=replay_id,
    )


class _FakeSubscribeCall:
    def __init__(self, responses: list[pb2.FetchResponse]):
        self._iter = iter(responses)
        self.cancelled = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    def cancel(self):
        self.cancelled = True


class _FakeStub:
    """Stands in for pubsub_api_pb2_grpc.PubSubStub — same call shapes
    (sync Subscribe returning an async-iterable/cancelable call, async
    unary GetSchema) but no real gRPC channel or TLS."""

    def __init__(self, responses: list[pb2.FetchResponse]):
        self._responses = responses
        self.get_schema_calls = 0
        self.last_metadata: tuple | None = None
        self.last_call: _FakeSubscribeCall | None = None
        self.last_request_iterator = None

    async def GetSchema(self, request, metadata=None):
        self.get_schema_calls += 1
        self.last_metadata = metadata
        return pb2.SchemaInfo(schema_json=json.dumps(TEST_SCHEMA), schema_id=request.schema_id)

    def Subscribe(self, request_iterator, metadata=None):
        self.last_metadata = metadata
        self.last_request_iterator = request_iterator
        self.last_call = _FakeSubscribeCall(self._responses)
        return self.last_call


@pytest.fixture
def two_events_stub():
    responses = [
        pb2.FetchResponse(
            events=[
                _consumer_event(
                    b"replay-1", "schema-abc", dt.datetime(2026, 9, 6, 10, 0, tzinfo=dt.UTC), "hello"
                ),
                _consumer_event(
                    b"replay-2", "schema-abc", dt.datetime(2026, 9, 6, 10, 1, tzinfo=dt.UTC), "world"
                ),
            ]
        )
    ]
    return _FakeStub(responses)


@pytest.fixture
def pubsub_client(authed_client, two_events_stub):
    authed_client._org_id = "00Dxx0000000001EAA"  # noqa: SLF001 - test seam
    return PubSubClient(authed_client, "fake-pubsub-host", 1234, stub=two_events_stub)


async def test_subscribe_decodes_events_in_order(pubsub_client):
    events = [event async for event in pubsub_client.subscribe("/event/Test__e", "LATEST", num_requested=10)]

    assert [e.payload["Message__c"] for e in events] == ["hello", "world"]
    assert events[0].replay_id == b"replay-1"
    assert events[0].created_date == dt.datetime(2026, 9, 6, 10, 0, tzinfo=dt.UTC)


async def test_subscribe_caches_schema_across_events_with_same_schema_id(pubsub_client, two_events_stub):
    _ = [event async for event in pubsub_client.subscribe("/event/Test__e", "LATEST", num_requested=10)]

    assert two_events_stub.get_schema_calls == 1


async def test_subscribe_sends_expected_grpc_auth_metadata(pubsub_client, two_events_stub):
    _ = [event async for event in pubsub_client.subscribe("/event/Test__e", "LATEST", num_requested=10)]

    metadata = dict(two_events_stub.last_metadata)
    assert metadata["accesstoken"] == "cached-token"
    assert metadata["tenantid"] == "00Dxx0000000001EAA"
    assert "instanceurl" in metadata


async def test_closing_the_generator_cancels_the_grpc_call(pubsub_client, two_events_stub):
    gen = pubsub_client.subscribe("/event/Test__e", "LATEST", num_requested=10)
    await anext(gen)
    await gen.aclose()

    assert two_events_stub.last_call.cancelled is True


async def test_request_stream_stays_open_after_the_first_message(pubsub_client, two_events_stub):
    """Regression test: half-closing the request (write) side of the stream
    right after the first FetchRequest was confirmed, against a real org, to
    make Salesforce stop delivering events entirely — even when GetTopic
    showed can_subscribe=True and a valid schema_id. The request iterator
    must stay open (not raise StopAsyncIteration) once the first message has
    been sent."""
    gen = pubsub_client.subscribe("/event/Test__e", "LATEST", num_requested=10)
    await anext(gen)  # drives the request_iterator far enough to send its first item

    request_iterator = two_events_stub.last_request_iterator
    await anext(request_iterator)  # consume the first FetchRequest

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(request_iterator), timeout=0.05)

    await gen.aclose()
