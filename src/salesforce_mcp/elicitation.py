from __future__ import annotations

import re

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

_WHERE_RE = re.compile(r"\bwhere\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)
_RETURNING_RE = re.compile(r"\breturning\b", re.IGNORECASE)


class ConfirmProceed(BaseModel):
    proceed: bool = Field(description="Confirm you want to proceed with this action")


def soql_looks_unscoped(soql: str) -> bool:
    """True if this SOQL query has no WHERE clause and/or no LIMIT clause —
    the two cheapest-to-check signals that it might return far more rows
    than intended. Not a SOQL parser, just a heuristic against the failure
    mode this feature exists for: browsing broadly instead of looking up
    something specific."""
    return not _WHERE_RE.search(soql) or not _LIMIT_RE.search(soql)


def sosl_looks_unscoped(sosl: str) -> bool:
    """True if this SOSL search has no RETURNING clause (searches every
    searchable object) and/or no LIMIT anywhere in it. A heuristic, not a
    per-object SOSL parser — good enough to catch the common unscoped case
    (`FIND {x} IN ALL FIELDS` with no object restriction) without hand-rolling
    SOSL grammar."""
    return not _RETURNING_RE.search(sosl) or not _LIMIT_RE.search(sosl)


async def confirm(ctx: Context | None, message: str, *, enabled: bool) -> bool:
    """Ask the user to confirm via MCP Elicitation; True means proceed.

    When `enabled` is False (SF_ELICITATION_ENABLED=false), always returns
    True without touching `ctx` at all — the escape hatch for anyone who
    finds the confirmation more annoying than useful.
    """
    if not enabled:
        return True
    result = await ctx.elicit(message, ConfirmProceed)
    if result.action != "accept":
        return False
    return result.data.proceed
