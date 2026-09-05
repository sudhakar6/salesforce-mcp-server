from __future__ import annotations

import re
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from .errors import as_prompt_error, raise_for_salesforce_error
from .salesforce_client import SalesforceClient

# Salesforce record IDs are always 15 or 18 alphanumeric characters. These two
# prompts build their own SOQL by interpolating an ID into a query string
# (unlike sf_query/sf_search, where the *caller* supplies the whole query) —
# validating the shape first rules out SOQL injection by construction, rather
# than trying to escape it.
_SALESFORCE_ID_RE = re.compile(r"^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$")


def _validate_salesforce_id(value: str, param_name: str) -> None:
    if not _SALESFORCE_ID_RE.match(value):
        raise ValueError(f"{param_name!r} doesn't look like a Salesforce record ID: {value!r}")


async def _query(client: SalesforceClient, soql: str) -> list[dict]:
    response = await client.request("GET", "/query", params={"q": soql})
    raise_for_salesforce_error(response)
    return response.json().get("records", [])


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> None:
    @mcp.prompt()
    @as_prompt_error
    async def summarize_account(account_id: str) -> str:
        """Summarize an Account's health: recent opportunities, open cases, and
        recommended next steps, using live data pulled from the org."""
        _validate_salesforce_id(account_id, "account_id")
        client = get_client()

        accounts = await _query(
            client,
            "SELECT Id, Name, Industry, AnnualRevenue, Phone "
            f"FROM Account WHERE Id = '{account_id}'",
        )
        if not accounts:
            raise ValueError(f"No Account found with Id {account_id!r}")
        account = accounts[0]

        opportunities = await _query(
            client,
            "SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity "
            f"WHERE AccountId = '{account_id}' ORDER BY CloseDate DESC LIMIT 5",
        )
        cases = await _query(
            client,
            "SELECT Id, Subject, Status, Priority FROM Case "
            f"WHERE AccountId = '{account_id}' ORDER BY CreatedDate DESC LIMIT 5",
        )

        return (
            f"Summarize the health of this Salesforce Account and suggest next steps.\n\n"
            f"Account: {account}\n\n"
            f"Recent Opportunities (up to 5): {opportunities}\n\n"
            f"Recent Cases (up to 5): {cases}\n\n"
            "Cover: overall relationship health, any at-risk signals (stalled deals, "
            "open high-priority cases), and 2-3 concrete recommended next steps. "
            "Use the sf_query or sf_search tools if you need more detail than what's above."
        )

    @mcp.prompt()
    @as_prompt_error
    async def draft_followup_email(opportunity_id: str) -> str:
        """Draft a follow-up email for an Opportunity, based on its stage and
        recent logged activity, using live data pulled from the org."""
        _validate_salesforce_id(opportunity_id, "opportunity_id")
        client = get_client()

        opportunities = await _query(
            client,
            "SELECT Id, Name, StageName, Amount, CloseDate, AccountId FROM Opportunity "
            f"WHERE Id = '{opportunity_id}'",
        )
        if not opportunities:
            raise ValueError(f"No Opportunity found with Id {opportunity_id!r}")
        opportunity = opportunities[0]

        activities = await _query(
            client,
            "SELECT Id, Subject, ActivityDate, Status FROM Task "
            f"WHERE WhatId = '{opportunity_id}' ORDER BY ActivityDate DESC LIMIT 5",
        )

        return (
            "Draft a professional follow-up email for this Opportunity, referencing "
            "its current stage and the most recent logged activity.\n\n"
            f"Opportunity: {opportunity}\n\n"
            f"Recent activity (up to 5 tasks): {activities}\n\n"
            "Keep it concise, reference something specific from the activity if there "
            "is any, and end with a clear call to action appropriate for this stage."
        )

    @mcp.prompt()
    def data_hygiene_check(sobject: str) -> str:
        """Ask the model to find data-quality issues (likely duplicates, missing
        required fields) for a given object, using the query/search tools directly
        rather than pre-fetched data."""
        return (
            f"Check {sobject} records for data-quality issues: likely duplicates "
            "(same name/email but different IDs), and records missing fields that "
            "should probably be filled in (e.g. no Industry on an Account, no "
            "CloseDate on an open Opportunity). Use sf_describe_object first if you "
            "need to know what fields this object has, then sf_query/sf_search to "
            "find candidates. Report what you find with specific record IDs, and "
            "suggest which ones look safe to merge or fix."
        )
