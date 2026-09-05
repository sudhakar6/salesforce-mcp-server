from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError, ToolError
from mcp.shared.exceptions import MCPError

# JSON-RPC "Invalid params" — same code ResourceNotFoundError uses internally.
_INVALID_PARAMS = -32602

_T = TypeVar("_T")


class SalesforceApiError(Exception):
    """Raised when Salesforce's REST/Bulk/Composite API returns an error response.

    Carries the HTTP status and a human-readable detail string parsed from
    Salesforce's error body, independent of whether the caller is a Tool or a
    Resource handler — `as_tool_error`/`as_resource_error` translate it into
    the framework-specific exception each one expects.
    """

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Salesforce API error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


def raise_for_salesforce_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    raise SalesforceApiError(response.status_code, _extract_error_detail(response))


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase or "unknown error"

    if isinstance(body, list) and body:
        parts = []
        for entry in body:
            if not isinstance(entry, dict):
                continue
            code = entry.get("errorCode", "UNKNOWN_ERROR")
            message = entry.get("message", "")
            fields = entry.get("fields") or []
            suffix = f" (fields: {', '.join(fields)})" if fields else ""
            parts.append(f"{code}: {message}{suffix}")
        if parts:
            return "; ".join(parts)

    if isinstance(body, dict):
        return str(body.get("message") or body.get("error_description") or body)

    return str(body)


def as_tool_error(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    """Translate SalesforceApiError/ValueError into ToolError for a tool function.

    ToolError's message reaches the model as a clean, actionable string instead
    of a generic "Error executing tool" crash message. ValueError is included
    since tools raise it for their own argument validation (e.g. an unsupported
    bulk operation name), not just Salesforce API failures.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs) -> _T:
        try:
            return await fn(*args, **kwargs)
        except SalesforceApiError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def as_resource_error(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    """Translate SalesforceApiError into ResourceError/ResourceNotFoundError for a resource handler."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs) -> _T:
        try:
            return await fn(*args, **kwargs)
        except SalesforceApiError as exc:
            if exc.status_code == 404:
                raise ResourceNotFoundError(str(exc)) from exc
            raise ResourceError(str(exc)) from exc

    return wrapper


def as_prompt_error(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    """Translate SalesforceApiError/ValueError into a clean MCPError for a prompt function.

    Prompt.render() (the SDK's own dispatcher) catches every exception a
    prompt function raises and replaces it with a generic "Error rendering
    prompt X" message — *except* MCPError, which passes through unchanged.
    Verified directly: a plain ValueError does NOT reach the client with its
    own message, unlike a ToolError from a tool. MCPError is the only way to
    surface a specific, readable message from a prompt.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs) -> _T:
        try:
            return await fn(*args, **kwargs)
        except SalesforceApiError as exc:
            raise MCPError(_INVALID_PARAMS, str(exc)) from exc
        except ValueError as exc:
            raise MCPError(_INVALID_PARAMS, str(exc)) from exc

    return wrapper
