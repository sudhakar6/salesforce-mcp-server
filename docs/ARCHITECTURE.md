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

## Platform events: a Tool, not a Resource subscription — and why

The brainstorm that produced `sf_org_health` and Prompts also included
"Resource subscriptions" — MCP's `resources/subscribe` +
`notifications/resources/updated` mechanism, where a client asks to be
pinged whenever a resource changes and re-reads it. The concrete ask that
followed ("give a platform event name, subscribe, bound it with a start
time and end time") turned out not to fit that mechanism at all, for a
reason worth stating plainly: a resource-update notification carries no
payload — it only tells the client "this changed, go call `resources/read`
again." There's no way to push individual event payloads to a client that
way, and no natural "end time" for a subscription that just runs until
unsubscribed. So `subscribe.py` implements `sf_subscribe_platform_event` as
an ordinary **Tool** instead: one bounded call — connect, collect matching
events, disconnect, return them — which is exactly what a start/end-time
request shape wants.

That decision was made *before* touching Salesforce's Pub/Sub API (the gRPC
API that replaced the old CometD-based Streaming API), and the API itself
then forced a second approximation. Verified directly against
[Salesforce's own proto file](https://github.com/forcedotcom/pub-sub-api)
and a community gRPC client
([pozil/pub-sub-api-node-client](https://github.com/pozil/pub-sub-api-node-client)),
both independently: the `Subscribe` RPC only accepts `LATEST` (tip of the
stream), `EARLIEST` (oldest retained event), or `CUSTOM` (a prior event's
own opaque `replay_id` bytes) — there is no "give me events since timestamp
X" parameter anywhere in this API. So `start_time`/`end_time` in
`tools/subscribe.py` are approximated, not passed to Salesforce directly:
`start_time` given → subscribe from `EARLIEST` and discard, on this end,
anything published before it (checking each event's own `CreatedDate`, or
`ChangeEventHeader.commitTimestamp` for a CDC channel); `start_time` omitted
→ `LATEST`, a live watch only. `end_time` has the same shape: Salesforce
can't stop the stream for you, so the tool watches each event's timestamp
and disconnects once it passes `end_time` (or `max_events`/`timeout_seconds`
is hit first — the stream is always explicitly cancelled, never left open).

The retention window matters here too: Salesforce keeps 72 hours of
replayable history (confirmed via the
[Event Message Durability guide](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html)
and the `replayid.corrupted` error the RPC reference documents for an
expired replay ID) — a `start_time` older than that is rejected before any
network call, rather than failing confusingly mid-stream.

`pubsub_client.py` is a second, separate transport client alongside
`salesforce_client.py`'s REST wrapper — a deliberate split, since gRPC
(binary framing over HTTP/2, streaming calls, per-call metadata for auth)
and Avro payload decoding have nothing in common with `httpx`'s request/
response REST calls. It reuses `SalesforceClient`'s existing OAuth token via
a new `get_pubsub_auth()` method rather than authenticating twice — the
Pub/Sub API's own metadata contract (documented directly in the generated
`PubSubStub`'s docstring) is `accesstoken`/`instanceurl`/`tenantid`, not a
bearer header. The generated protobuf/gRPC stubs
(`pubsub/pubsub_api_pb2*.py`) are committed rather than generated at install
time — `scripts/generate_pubsub_stubs.sh` regenerates them on the rare
occasion the vendored `pubsub_api.proto` changes, but running or testing the
server never needs `grpcio-tools`, only `grpcio` itself.

**A real bug this surfaced, found by testing against a live org rather than
assumed:** the first hands-on call to `sf_subscribe_platform_event` failed
with a bare "Error executing tool" — no detail, because the exception
wasn't a `SalesforceApiError`/`ValueError` and so `@as_tool_error` never saw
it. Reproduced directly: `grpc.aio.secure_channel(...)` was being created
inside `build_server()`, which runs *before* `main()`'s `asyncio.run()`
starts the event loop that actually drives the server. A `grpc.aio.Channel`
binds to whichever event loop is current at construction time — created
that early, it attaches to a throwaway loop, and the first real RPC then
fails with `RuntimeError: ... got Future ... attached to a different loop`.
The fix, in `pubsub_client.py`'s `_ensure_stub()`: create the channel/stub
lazily, on first actual `await` from inside the real running loop, instead
of eagerly in `__init__`. `SalesforceClient`'s `httpx.AsyncClient` never hit
this because HTTP transports bind lazily per-request; a gRPC channel does
not.

**A second real bug, also only found by testing against a live org:** after
the above fix, calls succeeded but consistently returned zero events —
even with `GetTopic` confirming `can_subscribe=True` and a valid `schema_id`,
and with real events already published on the topic. Isolated with a
standalone diagnostic script (`scripts/diagnose_pubsub.py`, bypassing all of
`tools/subscribe.py`'s time-filtering logic) that made the same raw
`Subscribe` call and got zero events *and* zero keepalives over 15 seconds —
the request stream itself was pathological, not a permissions or retention
issue. Root cause: `subscribe()`'s `request_iterator` sent one `FetchRequest`
then returned, which half-closes the client's write side of the bidi
stream. Salesforce appears to stop delivering events once it sees the
client signal "done sending," even though `num_requested` still had
capacity. The fix: after yielding the first `FetchRequest`, the iterator
now `await`s an `asyncio.Event` that's never set, keeping the write side
open indefinitely — the caller's `call.cancel()` (via `gen.aclose()`) is
what actually ends things, not the generator returning on its own. Guarded
by `tests/test_pubsub_client.py::test_request_stream_stays_open_after_the_first_message`,
which asserts the request iterator does *not* raise `StopAsyncIteration`
after its first item — confirmed to fail against the pre-fix code before
being confirmed to pass against the fix.

## Elicitation: confirming before broad reads or destructive writes

Motivated by a real incident during this project's own testing: given full
access to `sf_query`, the model chose to browse 50 Accounts with no
scoping when it wasn't sure which record the user meant. MCP's
**Elicitation** primitive — a tool pausing mid-execution to ask the user a
question through the client's own UI — is the mechanism built for exactly
this: a human checkpoint in front of a specific failure mode, not a general
"are you sure" wrapper around everything.

Verified directly against the installed SDK before writing any code here
(same discipline as every feature before it): a tool requests the
request-scoped context by adding a `ctx: Context`-annotated parameter — the
framework auto-injects a real one whenever a live request comes through, so
the `| None = None` default on that parameter exists purely so this
codebase's existing direct-call unit tests don't all need to construct one.
`ctx.elicit(message, schema)` returns `AcceptedElicitation[data] |
DeclinedElicitation | CancelledElicitation` (`mcp/server/elicitation.py`) —
check `.action`, and only the accepted variant has `.data`. Confirmed there's
no client-capability pre-check on the SDK side; it just sends
`elicitation/create` and awaits a reply — and confirmed, end to end against
a real client, that this actually surfaces as a prompt to a person: see
[USAGE.md#elicitation](USAGE.md#elicitation).

**Where it's wired in, and why those specific spots** (`elicitation.py`
holds the shared heuristics and the `confirm()` helper every one of these
calls):

- `sf_query` / `sf_search` — the actual incident. Triggered by a cheap,
  deterministic heuristic (`soql_looks_unscoped`/`sosl_looks_unscoped`): no
  `WHERE`/`RETURNING` clause, or no `LIMIT`. This is regex-based pattern
  matching, not a SOQL/SOSL parser — good enough to catch the common
  "browsing everything" case without hand-rolling grammar for either
  language, and documented as a heuristic rather than overclaiming
  precision.
- `sf_delete_record` — confirms **unconditionally**. A single-record delete
  has no "scope" to be broad or narrow about; the risk is the delete itself,
  not how many rows it touches.
- `sf_bulk_load` — confirms **unconditionally, only when `operation ==
  "delete"`**. insert/update/upsert are left alone; a bulk delete is
  irreversible regardless of how many records are in the batch, so (unlike
  the SOQL/SOSL case) no heuristic gates it.

**The disable switch**: `SF_ELICITATION_ENABLED=false` (config.py,
`Settings.elicitation_enabled`, defaults to **on**) skips every check above
without ever touching `ctx` — `confirm()`'s first line. Defaulting to on
matches why the feature exists: a fresh install gets the safety net without
having to know to turn it on; a user who finds it more annoying than useful
turns it off explicitly.

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
