from __future__ import annotations

import asyncio
import base64
import datetime as dt
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error
from ..pubsub_client import PubSubClient
from ..salesforce_client import SalesforceClient

RETENTION_WINDOW = dt.timedelta(hours=72)
DEFAULT_MAX_EVENTS = 100
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 120.0


def _parse_iso(label: str, value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO 8601 timestamp, got {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone offset, e.g. '2026-09-06T10:00:00+00:00'")
    return parsed


def _normalize_topic(api_name: str) -> str:
    return api_name if api_name.startswith("/") else f"/event/{api_name}"


def register(
    mcp: MCPServer,
    get_client: Callable[[], SalesforceClient],
    get_pubsub_client: Callable[[], PubSubClient],
) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_subscribe_platform_event(
        api_name: str,
        start_time: str | None = None,
        end_time: str | None = None,
        max_events: int = DEFAULT_MAX_EVENTS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        """Replay/subscribe to a Salesforce platform event or Change Data
        Capture channel and return a bounded batch of decoded events.

        `api_name` is a platform event's API name (e.g. "My_Event__e") —
        auto-prefixed with "/event/" — or a full topic path you already know
        (e.g. "/data/AccountChangeEvent" for a CDC channel).

        Salesforce's Pub/Sub API has no timestamp-based replay — only
        "earliest retained event", "tip of the stream", or a prior event's
        opaque replay ID. So `start_time`/`end_time` are approximated: with
        `start_time`, this replays from the earliest still-retained event and
        discards anything published before it; without `start_time`, it only
        watches for new events from now on. `start_time` must fall within the
        last 72 hours — Salesforce's Pub/Sub API retention window — or this
        fails before making any call.

        Always bounded: stops at the first of `end_time` reached, `max_events`
        collected, or `timeout_seconds` elapsed with nothing new arriving.
        """
        now = dt.datetime.now(dt.UTC)
        timeout_seconds = min(timeout_seconds, MAX_TIMEOUT_SECONDS)

        parsed_start = _parse_iso("start_time", start_time) if start_time else None
        parsed_end = _parse_iso("end_time", end_time) if end_time else None

        if parsed_start is not None and now - parsed_start > RETENTION_WINDOW:
            raise ValueError(
                "start_time is older than Salesforce's 72-hour Pub/Sub API retention "
                "window — events that old can no longer be replayed."
            )
        lower_bound = parsed_start or now
        if parsed_end is not None and parsed_end <= lower_bound:
            raise ValueError("end_time must be after start_time (or after now, if start_time is omitted).")

        topic = _normalize_topic(api_name)
        replay_preset = "EARLIEST" if parsed_start is not None else "LATEST"

        pubsub = get_pubsub_client()
        stream = pubsub.subscribe(topic, replay_preset, num_requested=max_events)
        events: list[dict] = []
        stopped_reason = "timeout"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds

        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    event = await asyncio.wait_for(anext(stream), timeout=remaining)
                except (StopAsyncIteration, TimeoutError):
                    break

                if parsed_start is not None and event.created_date is not None:
                    if event.created_date < parsed_start:
                        continue
                if parsed_end is not None and event.created_date is not None:
                    if event.created_date > parsed_end:
                        stopped_reason = "end_time_reached"
                        break

                events.append(
                    {
                        "replay_id_base64": base64.b64encode(event.replay_id).decode(),
                        "created_date": event.created_date.isoformat() if event.created_date else None,
                        "payload": event.payload,
                    }
                )
                if len(events) >= max_events:
                    stopped_reason = "max_events_reached"
                    break
        finally:
            await stream.aclose()

        return {
            "topic": topic,
            "replay_preset": replay_preset,
            "start_time": parsed_start.isoformat() if parsed_start else None,
            "end_time": parsed_end.isoformat() if parsed_end else None,
            "stopped_reason": stopped_reason,
            "events_returned": len(events),
            "events": events,
        }

    return {"sf_subscribe_platform_event": sf_subscribe_platform_event}
