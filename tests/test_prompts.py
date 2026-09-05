from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

from salesforce_mcp import prompts
from tests.conftest import DATA_BASE

QUERY_URL = f"{DATA_BASE}/query"
VALID_ID = "001000000000001AAA"


@pytest.fixture
def mcp(authed_client):
    server = MCPServer("test")
    prompts.register(server, lambda: authed_client)
    return server


def _query_response(records: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"totalSize": len(records), "done": True, "records": records})


async def _prompt_text(mcp: MCPServer, name: str, arguments: dict) -> str:
    result = await mcp.get_prompt(name, arguments)
    return result.messages[0].content.text


async def test_summarize_account_embeds_live_data(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(QUERY_URL).mock(
            side_effect=[
                _query_response([{"Id": VALID_ID, "Name": "Acme", "Industry": "Tech"}]),
                _query_response([{"Id": "006A", "Name": "Big Deal", "StageName": "Negotiation"}]),
                _query_response([{"Id": "500A", "Subject": "Login issue", "Status": "Open"}]),
            ]
        )
        text = await _prompt_text(mcp, "summarize_account", {"account_id": VALID_ID})

    assert "Acme" in text
    assert "Big Deal" in text
    assert "Login issue" in text
    assert "next steps" in text.lower()


async def test_summarize_account_rejects_malformed_id(mcp):
    with pytest.raises(MCPError, match="doesn't look like a Salesforce record ID"):
        await mcp.get_prompt("summarize_account", {"account_id": "'; DROP TABLE Account--"})


async def test_summarize_account_raises_when_account_not_found(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(QUERY_URL).mock(return_value=_query_response([]))
        with pytest.raises(MCPError, match="No Account found"):
            await mcp.get_prompt("summarize_account", {"account_id": VALID_ID})


async def test_draft_followup_email_embeds_live_data(mcp):
    async with respx.mock(assert_all_called=True) as router:
        router.get(QUERY_URL).mock(
            side_effect=[
                _query_response([{"Id": VALID_ID, "Name": "Big Deal", "StageName": "Negotiation"}]),
                _query_response([{"Id": "00TA", "Subject": "Called about pricing"}]),
            ]
        )
        text = await _prompt_text(mcp, "draft_followup_email", {"opportunity_id": VALID_ID})

    assert "Big Deal" in text
    assert "Called about pricing" in text
    assert "follow-up email" in text.lower()


async def test_data_hygiene_check_needs_no_salesforce_call(mcp):
    async with respx.mock(assert_all_called=True):
        text = await _prompt_text(mcp, "data_hygiene_check", {"sobject": "Contact"})

    assert "Contact" in text
    assert "duplicate" in text.lower()
