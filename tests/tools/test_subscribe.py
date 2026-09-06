from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from salesforce_mcp.pubsub_client import PubSubEvent
from salesforce_mcp.tools.subscribe import register

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _event(minute: int, replay_id: bytes = b"r", message: str = "hi") -> PubSubEvent:
    return PubSubEvent(
        replay_id=replay_id,
        created_date=NOW + dt.timedelta(minutes=minute),
        payload={"Message__c": message},
    )


class _FakePubSubClient:
    """Stands in for PubSubClient — subscribe() is an injectable async
    generator, so tests can control exactly what tools/subscribe.py sees
    without a real (or fake) gRPC layer underneath it."""

    def __init__(self, events: list[PubSubEvent], hang_after: bool = False):
        self._events = events
        self._hang_after = hang_after
        self.closed = False
        self.last_topic: str | None = None
        self.last_replay_preset: str | None = None

    async def subscribe(self, topic, replay_preset, *, replay_id=b"", num_requested):
        self.last_topic = topic
        self.last_replay_preset = replay_preset
        try:
            for event in self._events:
                yield event
            if self._hang_after:
                await asyncio.Event().wait()  # never resolves — forces the caller's timeout
        finally:
            self.closed = True


@pytest.fixture
def make_tools():
    def _make(pubsub_client):
        return register(MCPServer("test"), lambda: None, lambda: pubsub_client)

    return _make


async def test_rejects_start_time_older_than_retention_window(make_tools):
    tools = make_tools(_FakePubSubClient([]))
    # Relative to the real clock (not the fixed NOW fixture data uses below) —
    # this is what the tool actually validates against.
    too_old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=73)).isoformat()

    with pytest.raises(ToolError, match="72-hour"):
        await tools["sf_subscribe_platform_event"](api_name="My_Event__e", start_time=too_old)


async def test_rejects_end_time_before_start_time(make_tools):
    tools = make_tools(_FakePubSubClient([]))
    start = NOW.isoformat()
    end = (NOW - dt.timedelta(minutes=5)).isoformat()

    with pytest.raises(ToolError, match="end_time must be after"):
        await tools["sf_subscribe_platform_event"](api_name="My_Event__e", start_time=start, end_time=end)


async def test_rejects_naive_timestamp_without_timezone(make_tools):
    tools = make_tools(_FakePubSubClient([]))

    with pytest.raises(ToolError, match="timezone offset"):
        await tools["sf_subscribe_platform_event"](api_name="My_Event__e", start_time="2026-09-06T10:00:00")


async def test_bare_api_name_gets_event_prefixed(make_tools):
    fake = _FakePubSubClient([])
    tools = make_tools(fake)

    await tools["sf_subscribe_platform_event"](api_name="My_Event__e", timeout_seconds=0.1)

    assert fake.last_topic == "/event/My_Event__e"
    assert fake.last_replay_preset == "LATEST"


async def test_full_topic_path_passed_through_unchanged(make_tools):
    fake = _FakePubSubClient([])
    tools = make_tools(fake)

    await tools["sf_subscribe_platform_event"](api_name="/data/AccountChangeEvent", timeout_seconds=0.1)

    assert fake.last_topic == "/data/AccountChangeEvent"


async def test_start_time_given_uses_earliest_and_filters_older_events(make_tools):
    events = [_event(minute=0, message="too-old"), _event(minute=10, message="in-window")]
    fake = _FakePubSubClient(events)
    tools = make_tools(fake)
    start_time = (NOW + dt.timedelta(minutes=5)).isoformat()

    result = await tools["sf_subscribe_platform_event"](
        api_name="My_Event__e", start_time=start_time, timeout_seconds=0.1
    )

    assert fake.last_replay_preset == "EARLIEST"
    assert result["events_returned"] == 1
    assert result["events"][0]["payload"]["Message__c"] == "in-window"


async def test_stops_at_max_events(make_tools):
    events = [_event(minute=m) for m in range(5)]
    fake = _FakePubSubClient(events)
    tools = make_tools(fake)

    result = await tools["sf_subscribe_platform_event"](
        api_name="My_Event__e", max_events=2, timeout_seconds=1
    )

    assert result["stopped_reason"] == "max_events_reached"
    assert result["events_returned"] == 2
    assert fake.closed is True


async def test_stops_at_end_time_reached(make_tools):
    events = [_event(minute=0), _event(minute=30)]
    fake = _FakePubSubClient(events)
    tools = make_tools(fake)
    end_time = (NOW + dt.timedelta(minutes=15)).isoformat()

    result = await tools["sf_subscribe_platform_event"](
        api_name="My_Event__e", end_time=end_time, timeout_seconds=1
    )

    assert result["stopped_reason"] == "end_time_reached"
    assert result["events_returned"] == 1
    assert fake.closed is True


async def test_stops_on_timeout_when_nothing_more_arrives(make_tools):
    fake = _FakePubSubClient([_event(minute=0)], hang_after=True)
    tools = make_tools(fake)

    result = await tools["sf_subscribe_platform_event"](api_name="My_Event__e", timeout_seconds=0.05)

    assert result["stopped_reason"] == "timeout"
    assert result["events_returned"] == 1
    assert fake.closed is True
