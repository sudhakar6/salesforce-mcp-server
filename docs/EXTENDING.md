# Extending: adding your own first-class tool

`sf_call_apex_rest` ([USAGE.md](USAGE.md#calling-a-custom-apex-rest-api)) lets
you call any custom Apex REST endpoint *today*, with no code changes — but
it's generic: the model sees a tool called `sf_call_apex_rest` that takes a
raw `method`/`path`/`body`, not a purpose-built tool with its own name and a
tight schema. If you have one custom API you use constantly and want it to
show up in `tools/list` the same way `sf_query` does — its own name,
description, and typed parameters, so the model doesn't have to reconstruct
the right path/body every time — write it as a dedicated tool instead. This
is that guide.

## The pattern every existing tool module follows

Every file under `src/salesforce_mcp/tools/` — `query.py`, `records.py`,
`bulk.py`, `custom_api.py`, all of them — follows the same shape:

```python
# src/salesforce_mcp/tools/your_module.py
from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_your_tool_name(param: str) -> dict:
        """One clear sentence the MODEL reads to decide when to call this.
        This docstring is the tool's `description` in tools/list — write it
        for an LLM deciding whether it's relevant, not for a human reading
        the source.
        """
        client = get_client()
        response = await client.request("GET", f"/your/path/{param}")
        raise_for_salesforce_error(response)
        return response.json()

    return {"sf_your_tool_name": sf_your_tool_name}
```

Four things to know about the pieces you're reusing:

- **`client.request(method, path, *, versioned=True, ...)`** is the one
  place that knows how to authenticate, retry on transient errors, and talk
  HTTP — you never touch `salesforce_client.py` itself. `versioned=True`
  (the default) prepends `/services/data/{api_version}` to `path`; pass
  `versioned=False` and build the full instance-relative path yourself for
  anything outside that namespace (Apex REST's `/services/apexrest/...`,
  same as `custom_api.py` does).
- **`raise_for_salesforce_error(response)`** turns a non-2xx Salesforce
  response into a `SalesforceApiError` with a parsed, readable message.
- **`@as_tool_error`** catches that (and any `ValueError` you raise for your
  own argument validation) and turns it into a `ToolError` — the clean,
  no-stack-trace message the model actually sees. Skipping this decorator
  means a Salesforce error becomes a generic "Error executing tool" crash
  instead. See [ARCHITECTURE.md#error-handling](ARCHITECTURE.md#error-handling).
- **`register()` returns a `dict[str, Callable]`** so tests can call your
  tool function directly — `await tools["sf_your_tool_name"](param="x")` —
  without spinning up a full MCP session. This works because `@mcp.tool()`
  and `@as_tool_error` both return the original function, not a wrapper.

## Step by step

1. **Create the module** — `src/salesforce_mcp/tools/your_module.py`,
   following the shape above. Give the tool function(s) an `sf_`-prefixed
   name and a docstring aimed at the model.
2. **Register it** — in `src/salesforce_mcp/server.py`, add your module to
   the import and to the tuple `build_server()` iterates:
   ```python
   from .tools import bulk, composite, custom_api, describe, ops, query, records, your_module
   ...
   for module in (query, records, describe, bulk, composite, ops, custom_api, your_module):
       module.register(mcp, get_client)
   ```
3. **Write tests** — `tests/tools/test_your_module.py`, mocking Salesforce
   with `respx` exactly like every existing test file does (see
   `tests/tools/test_custom_api.py` for the shortest example, or
   `tests/tools/test_bulk.py` for a multi-step one). The `authed_client`
   fixture in `tests/conftest.py` gives you a `SalesforceClient` with a
   token already seeded, so you don't need to mock the OAuth handshake.
4. **Run the usual checks**:
   ```bash
   pytest tests/ -v
   ruff check src tests
   ```
5. **If it's a Resource, not a Tool** (something a client should be able to
   pull into context without an explicit call, like the schema data in
   `resources.py`) — same idea, but `@mcp.resource(uri)` and
   `@as_resource_error` instead; see `src/salesforce_mcp/resources.py`.
6. **If it's a Prompt** (a ready-made task template a person picks directly,
   rather than something the model decides to call) — `@mcp.prompt()` and
   `@as_prompt_error` instead of the Tool/Resource decorators; see
   `src/salesforce_mcp/prompts.py`. One real gotcha here worth knowing before
   you hit it yourself: a plain `ValueError`/`SalesforceApiError` does **not**
   reach the client with its message for a Prompt the way it does for a
   Tool — only `MCPError` does. `as_prompt_error` handles this; see
   [ARCHITECTURE.md#prompts-the-third-mcp-primitive-and-a-real-surprise-in-how-errors-work](ARCHITECTURE.md#prompts-the-third-mcp-primitive-and-a-real-surprise-in-how-errors-work)
   for why.

## Worked example: a dedicated tool for the AccountHealth API from USAGE.md

Turning the generic call from [USAGE.md](USAGE.md#calling-a-custom-apex-rest-api)
into its own purpose-built tool:

```python
# src/salesforce_mcp/tools/account_health.py
from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from ..errors import as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient


def register(mcp: MCPServer, get_client: Callable[[], SalesforceClient]) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_get_account_health(account_id: str) -> dict:
        """Get an Account's health score from the org's custom AccountHealth API.
        Returns {"accountId", "name", "healthScore": "good"|"watch"}.
        """
        client = get_client()
        response = await client.request(
            "GET", f"/services/apexrest/AccountHealth/{account_id}", versioned=False
        )
        raise_for_salesforce_error(response)
        return response.json()

    return {"sf_get_account_health": sf_get_account_health}
```

Register it in `server.py` alongside the others, add
`tests/tools/test_account_health.py` mirroring `test_custom_api.py`, and the
model now sees `sf_get_account_health(account_id: str)` directly in
`tools/list` — a tighter, purpose-built alternative to asking it to construct
`sf_call_apex_rest(method="GET", path="/AccountHealth/...")` itself.

## A real example commit: `sf_org_health`

The `AccountHealth` example above is illustrative; for an actual tool added
this same way, built, tested, and shipped, see commit
[`2f86f43`](https://github.com/sudhakar6/salesforce-mcp-server/commit/2f86f43)
— "Add `sf_org_health`: org info, all limits, and license seat usage." It
touches exactly the places this guide describes, and nothing else:

- [`tools/org_health.py`](../src/salesforce_mcp/tools/org_health.py) — the
  new module (one tool, `sf_org_health`, aggregating five Salesforce calls
  into one report)
- [`server.py`](../src/salesforce_mcp/server.py) — one import added, one
  entry added to the registration tuple
- [`tests/tools/test_org_health.py`](../tests/tools/test_org_health.py) —
  happy path plus one error case, mocked with `respx` exactly like every
  other test file
- `README.md` / `USAGE.md` / `ARCHITECTURE.md` — feature list, an example
  prompt, and a short design note

If you're adding your own tool, that commit is a good template to diff
against: it's the smallest real example of "one new tool, end to end" in
this repo's history.

If you're adding your own tool, `git log --oneline -- src/salesforce_mcp/tools/org_health.py`
finds the commit that added it — a good one to diff against as the smallest
real example of "one new tool, end to end" in this repo's history.
