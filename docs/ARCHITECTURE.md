# Architecture — how this was built, and why

*This doc is background reading, not a prerequisite. If you just want to run
the server, [README.md](../README.md) and [docs/USAGE.md](USAGE.md) are all
you need — come back here if you're curious how it works or why a
particular decision was made.*

## Not a Salesforce product

Salesforce ships its own feature with a similar-sounding name — ["Hosted/Custom
MCP Servers"](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/custom-servers.html)
— so this was checked before writing any code. It turns out to be a different
thing entirely: a **no-code, admin-configured** Setup feature, where an admin
wires up existing Apex Actions, Flows, or similar into a Salesforce-*hosted*
server URL. No server code involved, nothing a developer builds or publishes.

That same Salesforce page points elsewhere for "how to build your own MCP
server from scratch": the general [Model Context Protocol
specification](https://modelcontextprotocol.io). That's what this project is —
an independent implementation of that open spec, built with the official
[`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk), that
talks to Salesforce only through its public REST, Bulk API 2.0, and Composite
APIs.

**It is not a Salesforce product, and is not affiliated with, endorsed by, or
supported by Salesforce, Inc.** Using it is your own responsibility, subject
to your org's API usage policies and Salesforce's terms of service.

## Request flow

```
MCP client (Claude Desktop / MCP Inspector / any MCP client)
        │  MCP protocol (stdio locally, or Streamable HTTP + bearer token remotely)
        ▼
salesforce_mcp.server  (MCPServer instance, tools + resources registered)
        │
        ▼
salesforce_mcp.salesforce_client.SalesforceClient
        │  OAuth 2.0 Client Credentials Flow, retry/backoff, error mapping
        ▼
Salesforce REST API / Bulk API 2.0 / Composite API
```

Each `tools/*.py` module owns one family of Salesforce endpoints and knows the
*shape* of those requests (paths, bodies, pagination quirks). `SalesforceClient`
only knows how to authenticate, send a request, retry it, and hand back the raw
`httpx.Response` — it has no idea what a SOQL query or a Bulk job even is. That
split is what keeps `sf_bulk_load`'s CSV/job-polling logic from leaking into
the client, and keeps the client's auth/retry logic from being duplicated
across seven-plus call sites.

## Why Client Credentials Flow (and why External Client App, not Connected App)

Client Credentials Flow needs no interactive login and no stored end-user
password — just a client ID/secret and a "Run As" service user, which is the
right shape for a headless integration. A follow-up check confirmed Salesforce
now restricts creating new legacy **Connected Apps** (as of Spring '26); new
server-to-server integrations should be configured as an **External Client
App** instead — same flow, newer Setup object. See
[SETUP.md](SETUP.md) for the concrete steps.

## Why FastMCP-style decorators, and the mcp 2.x surprise

The `mcp` Python SDK was originally going to be used via the well-known
`FastMCP` class. Installing the current release (`mcp` 2.x) turned up a
breaking rename: `FastMCP` → `MCPServer` (`mcp.server.mcpserver.MCPServer`),
discovered by actually installing the package and inspecting it rather than
assuming a remembered API still matched. The decorator-based ergonomics are
unchanged (`@mcp.tool()`, `@mcp.resource(uri)`), and both decorators return the
*original* function rather than a wrapper — verified directly — which is what
makes the `register(mcp, get_client) -> dict[str, Callable]` pattern used
throughout `tools/` possible: tests call the returned functions directly,
without needing to drive them through the full MCP request-dispatch machinery.

## Error handling

Salesforce's REST error body (`[{"errorCode": ..., "message": ..., "fields":
[...]}]`) is parsed once, in `errors.py`, into a `SalesforceApiError` that's
transport-agnostic. Two thin decorators translate it for whichever protocol
surface is calling:

- `as_tool_error` → `ToolError` (and `ValueError`, for the tools' own argument
  validation) — the MCP SDK turns this into a clean `is_error=True` result with
  your message, no stack trace, verified directly against the installed SDK.
- `as_resource_error` → `ResourceError`, or `ResourceNotFoundError` specifically
  for a 404 (e.g. describing an object that doesn't exist).

Retries (exponential backoff, 3 attempts) are scoped narrowly: only HTTP 5xx
and Salesforce's `REQUEST_LIMIT_EXCEEDED` (403) are transient. Every other 4xx
— a malformed SOQL query, a missing field, an authorization failure — surfaces
immediately; retrying those would just repeat the same failure.

## Interactive REST tools *and* Bulk API 2.0 tools, side by side

`sf_create_record`/`sf_update_record`/etc. are one-record-per-call and return
immediately — right for interactive, conversational use. `sf_bulk_query`/
`sf_bulk_load` exist for the case those don't fit: large result sets or large
batch loads, via Salesforce's job-based Bulk API 2.0 (submit → poll → fetch
CSV results). Both live in the same server because they answer different
questions ("give me this one record" vs. "load these 10,000 rows"), not
because one replaces the other.

## Describe/discovery as both a Tool and a Resource

`sf_describe_object` / `sf_list_objects` and the two MCP Resources
(`salesforce://schema/{sobject}`, `salesforce://objects`) call the *same*
underlying functions in `tools/describe.py`. This is deliberate, not
duplication: a Tool is something the model decides to invoke mid-conversation;
a Resource is something a client can pull into context up front (e.g. "here's
the org's object list" before the model even starts reasoning). Exposing one
capability both ways is a small, concrete way to show what MCP's Resources
primitive is actually for, rather than only ever reaching for Tools.

`list_objects()` trims Salesforce's raw global-describe response (~25
fields per object, including a nested `urls` block) down to
name/label/custom/queryable/createable/updateable/deletable, and
`sf_list_objects` adds optional `name_contains`/`custom_only` filters on
top. Found via real testing, not anticipated: a Developer Edition org's
800+ standard objects, returned raw, was large enough to exhaust a model's
context on its own. Since both the Tool and the Resource share this one
function, fixing it once fixed both.

## A generic escape hatch for custom Apex REST endpoints

Every tool up to this point is bound to a fixed, standard Salesforce
endpoint — `sf_query` always calls `/query`, `sf_create_record` always calls
`/sobjects/{sobject}`, and so on. None of them can reach something specific
to one org, like a custom Apex REST class (`@RestResource`) that isn't part
of Salesforce's standard API surface.

`sf_call_apex_rest` (`tools/custom_api.py`) closes that gap generically,
instead of one endpoint at a time. It forwards `method`/`path`/`body`/`params`
straight to `/services/apexrest{path}`, through the same `SalesforceClient`
every other tool uses — same auth, same retry/backoff, same error mapping. It
has no idea what any particular custom endpoint does, on purpose: this project
can't anticipate every org's custom API, so instead of growing one bespoke
tool per org, it exposes the one generic mechanism Salesforce itself provides
for org-specific REST capabilities. See
[USAGE.md#calling-a-custom-apex-rest-api](USAGE.md#calling-a-custom-apex-rest-api)
for how to write and call one.

Salesforce's *Hosted* MCP Servers feature (the disclaimer at the top of this
doc) also supports Apex Invocable Actions, Flows, and `@AuraEnabled` methods
as custom-capability mechanisms. Those weren't added here because this
project only talks to Salesforce through its public REST/Bulk/Composite
APIs, and those three don't expose as cleanly through that surface as Apex
REST does. A `sf_call_invocable_action` tool
(`/services/data/v{ver}/actions/custom/{apex|flow}/{name}`) would follow the
exact same pattern as `sf_call_apex_rest`, if that's ever wanted.

## Two ops tools, two different jobs

`sf_api_usage` (`tools/ops.py`) and `sf_org_health` (`tools/org_health.py`)
both report on the org itself rather than its data, but they answer
different questions at different costs. `sf_api_usage` is cache-first —
usually free, reading the `Sforce-Limit-Info` header already captured from
whatever the last call was — for a quick "how close to the limit are we"
check mid-conversation. `sf_org_health` always makes five calls (the full
`/limits` payload plus `Organization`, `UserLicense`,
`PermissionSetLicense`, and `PackageLicense` queries) for a broader "what
does this org have and how much of it is used" report — org edition/type,
every limit category, not just API requests, and license seat consumption.
Reach for `sf_api_usage` in a loop; reach for `sf_org_health` once, for the
full picture.

## Prompts: the third MCP primitive, and a real surprise in how errors work

`prompts.py` adds MCP's **Prompts** primitive — ready-made task templates
(`summarize_account`, `draft_followup_email`, `data_hygiene_check`) a client
surfaces directly to a person, rather than something the model decides to
call. The first two show one pattern (fetch live data, embed it in the
returned text); the third shows the other (a pure task description, no
Salesforce call — the model reaches for `sf_query`/`sf_search` itself). Both
are legitimate; see [USAGE.md#prompts](USAGE.md#prompts) for the concrete
difference.

The genuine surprise, found by testing rather than assumed: a plain
`ValueError` raised inside a Tool becomes a clean message via `ToolError`
(see "Error handling" above), but the *same pattern does not work for
Prompts*. `Prompt.render()` — the SDK's own dispatcher, which runs before
`get_prompt()`'s error handling ever sees anything — catches every exception
a prompt function raises and replaces it with a generic "Error rendering
prompt X", discarding the original message, *except* for `MCPError`, which
passes through unchanged. Confirmed by writing a test that expected a
specific `ValueError` message and watching it come back as the generic one
instead. `as_prompt_error` (`errors.py`) is the fix: it catches
`SalesforceApiError`/`ValueError` and re-raises as `MCPError(-32602, ...)`
— the *only* exception type this primitive lets through with your message
intact.

A second surprise, this time on the client side rather than this server's
code: a raw JSON-RPC probe over real stdio confirmed the server was entirely
correct — `initialize` advertises the `prompts` capability and
`prompts/list` returns all three prompts with full schemas. Neither Claude
Desktop's `/`-menu, its Code tab, nor the standalone Claude Code CLI
surfaced a way to invoke one, despite `/mcp__server__prompt` being
documented elsewhere for Claude Code — until the **Connectors panel**
turned out to be the actual place: it lists a connected server's prompts on
hover, and picking one prompts for its required argument(s) before running
it. Confirmed working end to end this way — `summarize_account` correctly
asked for `account_id` and used it. Typing a prompt's name as plain chat
text still doesn't invoke it, and never will; the model just reacts to the
literal string conversationally (with full access to `sf_query` and no
`account_id` constraint), which is a different code path that happens to
share a name, not a broken prompt. See
[USAGE.md#prompts](USAGE.md#prompts) for the confirmed how-to.

## Server-side auth is separate from Salesforce auth

The OAuth Client Credentials Flow in `salesforce_client.py` is this server
authenticating itself *to Salesforce*. Once the server is also reachable
over the network (Streamable HTTP mode), it needs its own gate — otherwise
anyone who finds the URL can use it. `http_auth.py`'s bearer-token middleware
is that gate: a single shared secret (`MCP_SERVER_TOKEN`), checked before a
request ever reaches the MCP session layer. It's deliberately not full OAuth
resource-server machinery (the SDK does support that, via `TokenVerifier` +
`AuthSettings`, but that needs a real issuer/authorization server) — a shared
secret is the right amount of machinery for a personal project's hosted
instance, not for a multi-tenant production service.

One related note: the SDK's built-in DNS-rebinding protection
(`TransportSecuritySettings`) auto-enables itself only when binding to a
loopback host (`127.0.0.1`/`localhost`/`::1`) — verified directly against the
installed SDK. This server defaults to binding `0.0.0.0` (the standard
container convention), so that protection is off unless explicitly configured;
the bearer-token gate is the primary defense here, with the Host/Origin
allowlist available as optional defense-in-depth (see
[DEPLOYMENT.md](DEPLOYMENT.md)).

## What was learned

- Don't trust a remembered SDK API for a fast-moving ecosystem — `pip install`
  and `inspect.signature()` against the real package caught the FastMCP →
  MCPServer rename, the exact retry-relevant exception types, and the
  streamable-http/DNS-rebinding defaults, all before writing tool code around
  a guess.
- A thin, transport-agnostic error type (`SalesforceApiError`) plus two small
  translation decorators (`as_tool_error`, `as_resource_error`) removed almost
  all repeated try/except boilerplate across a dozen tools.
- Bulk API 2.0's job lifecycle (submit → poll → CSV fetch) is a different
  shape from the synchronous REST calls, but sharing one `SalesforceClient`
  underneath both meant the auth/retry logic only had to be written once.
