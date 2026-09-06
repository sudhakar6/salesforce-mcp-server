# Usage

> New to MCP, or to the Host/Client/Server terms used below? See
> [MCP_PRIMER.md](MCP_PRIMER.md) first.

## MCP Inspector (quickest way to try every tool)

```bash
source .venv/bin/activate
npx @modelcontextprotocol/inspector python -m salesforce_mcp.server
```

> **What's `npx`, and why does this need it?** The
> [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — the
> standard debugging UI for any MCP server — is a Node.js tool published to
> npm, not something this Python project depends on or installs.
> [`npx`](https://docs.npmjs.com/cli/v10/commands/npx) is npm's "run a
> package without installing it first" command: it downloads
> `@modelcontextprotocol/inspector` from the npm registry (caching it for
> next time) and runs it immediately, the same way you might reach for
> `pipx run` or a one-off `docker run` for a Python or container tool you
> don't want to permanently install. It needs [Node.js](https://nodejs.org)
> present on your machine (`npx` ships with it), but nothing else — no
> separate signup or config.

Open the URL it prints, connect, and call tools directly from the UI. Good
first calls, in order:

1. `sf_list_objects` — confirms auth works and shows what's in the org
2. `sf_describe_object` with `sobject: "Account"` — field metadata
3. `sf_query` with `soql: "SELECT Id, Name FROM Account LIMIT 5"`
4. Read the resource `salesforce://schema/Account` — same data as (2), via the
   Resources tab instead of Tools
5. `sf_org_health` — org info, every limit category, and license seat usage
   in one call

## Claude Desktop (stdio)

**1. Open the config file** — in the app, **Settings → Developer → Edit
Config**. That opens
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS
directly in your editor (confirmed navigation path — the file can be in a
non-obvious location depending on the app build, so use this instead of
guessing the path yourself).

**2. Add an `mcpServers` key — don't replace the file.** This file likely
already has other content (app preferences, etc.) that must stay intact.
Add `mcpServers` alongside whatever's already there, for example:

```json
{
  "mcpServers": {
    "salesforce": {
      "command": "/absolute/path/to/salesforce-mcp-server/.venv/bin/python",
      "args": ["-m", "salesforce_mcp.server"],
      "env": {
        "SF_LOGIN_URL": "https://your-domain.my.salesforce.com",
        "SF_CLIENT_ID": "your-client-id",
        "SF_CLIENT_SECRET": "your-client-secret"
      }
    }
  },
  "...": "whatever else was already in this file, unchanged"
}
```

Use the absolute path to *this project's* venv Python (`which python` with
the venv activated, or `.venv/bin/python` from the project root) — not a
system Python, which won't have the package installed.

**3. Validate the JSON before restarting** — a syntax error here can break
the file for the whole app. Quick check:
```bash
python3 -c "import json; json.load(open('/absolute/path/to/claude_desktop_config.json')); print('valid JSON')"
```

**4. Restart the app completely.** Config is only read at startup — editing
the file while the app is running has no effect until it restarts.

**5. Confirm the connection, then try a Tool and a Prompt** — these are
discovered differently:
- **Tools** — just ask something that needs Salesforce data in normal chat,
  e.g. *"List the open opportunities over $10,000 closing this quarter"* or
  *"Find every Account or Contact mentioning 'Acme'"* (exercises `sf_search`).
  The model decides on its own to call the right tool.
- **Prompts** — these need a different, dedicated picker; see
  [Prompts](#prompts) below for the confirmed way to find and invoke one
  (it's not a `/`-command, and typing the prompt's name as a chat message
  does **not** invoke it — that's a completely different, unconstrained code
  path, not a shortcut to the real thing).

**If you built the Docker image instead of setting up Python** (Quickstart's
Option B), point Claude Desktop at `docker run` instead — the bare `-e VAR`
form (no `=value`) forwards each variable from the `env` block below into the
container, verified directly:

```json
{
  "mcpServers": {
    "salesforce": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "SF_LOGIN_URL", "-e", "SF_CLIENT_ID", "-e", "SF_CLIENT_SECRET",
        "-e", "MCP_TRANSPORT",
        "salesforce-mcp-server"
      ],
      "env": {
        "SF_LOGIN_URL": "https://your-domain.my.salesforce.com",
        "SF_CLIENT_ID": "your-client-id",
        "SF_CLIENT_SECRET": "your-client-secret",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

## Connecting an agent to a remote (hosted) server

Once deployed (see [DEPLOYMENT.md](DEPLOYMENT.md)) you have a
`https://<your-host>/mcp` endpoint gated by a bearer token. How an agent
connects to that depends on the agent — this server uses a plain static
bearer token, and it turns out not every MCP-capable client can be pointed at
that the same way:

**MCP Inspector** (works out of the box):

```bash
npx @modelcontextprotocol/inspector --url https://<your-host>/mcp \
  --header "Authorization: Bearer <MCP_SERVER_TOKEN>"
```

**Claude Code CLI** (works out of the box — supports static headers natively):

```bash
claude mcp add --transport http salesforce https://<your-host>/mcp \
  --header "Authorization: Bearer <MCP_SERVER_TOKEN>"
```

**Claude Desktop's GUI ("Settings → Connectors → Add custom connector")** —
this is the one to know about *before* you try it: as of writing, that flow
always attempts OAuth 2.0 against the server's origin and has no field for a
static bearer token or custom header. Pointing it straight at
`https://<your-host>/mcp` will fail, not because of anything wrong with this
server, but because Claude Desktop's connector UI doesn't support
shared-secret auth today. Two ways around that:

1. **Bridge it with [`mcp-remote`](https://github.com/punkpeye/mcp-remote)** —
   a small stdio↔HTTP proxy Claude Desktop's *stdio* config (the same
   `mcpServers` shape used for local servers in the previous section) can
   launch, which then attaches the header itself:
   ```json
   {
     "mcpServers": {
       "salesforce": {
         "command": "npx",
         "args": [
           "-y", "mcp-remote", "https://<your-host>/mcp",
           "--header", "Authorization:${AUTH_HEADER}"
         ],
         "env": { "AUTH_HEADER": "Bearer <MCP_SERVER_TOKEN>" }
       }
     }
   }
   ```
   (Note no space around the `:` in `--header` and the space-containing
   `Bearer <token>` moved into the `env` block instead — a documented
   workaround for a header-escaping bug in how some hosts, Claude Desktop on
   Windows included, invoke `npx`.)
2. **Implement full OAuth** on the server instead of a static token — the
   `mcp` SDK supports this (`TokenVerifier`/`AuthSettings`, noted in
   [ARCHITECTURE.md](ARCHITECTURE.md#server-side-auth-is-separate-from-salesforce-auth)),
   but it needs a real authorization server behind it, which is more than a
   personal/practice deployment needs — `mcp-remote` is the pragmatic choice
   here.

## Calling a custom Apex REST API

`sf_call_apex_rest` doesn't need any server-side configuration — no env var,
no restart. It's a generic pass-through, so "configuring" it just means: (1)
your org has to have a custom Apex REST class deployed and the Run As
integration user (see [SETUP.md](SETUP.md)) has to have permission to execute
it, and (2) you tell the model the path/method when you ask for it, the same
way you'd tell a person which endpoint to hit.

**1. A minimal custom Apex REST class**, deployed in the org (e.g. via the
Developer Console or Setup → Apex Classes):

```apex
@RestResource(urlMapping='/AccountHealth/*')
global with sharing class AccountHealthApi {
    @HttpGet
    global static Map<String, Object> getHealth() {
        RestRequest req = RestContext.request;
        Id accountId = req.requestURI.substring(req.requestURI.lastIndexOf('/') + 1);
        Account acc = [SELECT Id, Name, AnnualRevenue FROM Account WHERE Id = :accountId];
        return new Map<String, Object>{
            'accountId' => acc.Id,
            'name' => acc.Name,
            'healthScore' => acc.AnnualRevenue != null && acc.AnnualRevenue > 1000000 ? 'good' : 'watch'
        };
    }
}
```

**2. Grant the integration user access** — add "AccountHealthApi" (Enabled
Apex Class Access) to the permission set assigned to the Run As user from
[SETUP.md](SETUP.md).

**3. Call it** — either directly:

```json
{ "method": "GET", "path": "/AccountHealth/001xx0000000001AAA" }
```

...or just ask the agent in natural language once it knows the endpoint
exists, e.g. *"Call the AccountHealth API for account 001xx0000000001AAA and
tell me the health score"* — the model reads `sf_call_apex_rest`'s
description, fills in `method`/`path` itself, and calls it exactly like any
built-in tool.

## Prompts

*Not to be confused with the "example prompts" (things you type) in the next
section — these are MCP's **Prompts** primitive: ready-made task templates
the server exposes, distinct from Tools and Resources. See
[MCP_PRIMER.md#the-three-roles-host-client-server](MCP_PRIMER.md#the-three-roles-host-client-server)
for what a Prompt is if that distinction is new.*

Three are built in — visible in a client's Prompts picker (in the Inspector,
a separate tab from Tools/Resources) rather than something you have to know
to ask for:

| Prompt | Argument | What it does |
|---|---|---|
| `summarize_account` | `account_id` | Fetches the Account plus its 5 most recent Opportunities and Cases, and asks the model to summarize health and suggest next steps |
| `draft_followup_email` | `opportunity_id` | Fetches the Opportunity plus its 5 most recent logged Tasks, and asks for a follow-up email referencing them |
| `data_hygiene_check` | `sobject` | A pure task template, no pre-fetched data — asks the model to use `sf_query`/`sf_search` itself to find likely duplicates or incomplete records |

The first two show one pattern (pull live data into the prompt so the model
doesn't have to look it up first); the third shows the other (just phrase
the task well and let the model reach for tools itself). Both are legitimate
— which one fits depends on whether you already know what data the model
will need.

**Client support, tested directly rather than assumed** — and corrected once
already, so this is worth being precise about. The server side was always
confirmed correct: `initialize` advertises the `prompts` capability and
`prompts/list` returns all three with full schemas over the real stdio wire
protocol. Neither `/`-menus nor `/mcp__server__prompt` surfaced them in
Claude Desktop's chat tab, its Code tab, or the Claude Code CLI.

**The confirmed way, for Claude Desktop:** find the **Connectors** entry
near the message box (a `+`/attachment-style picker) — it offers an option
like *"Add from Salesforce"*; hovering it lists this server's prompts.
Picking one prompts you for its required argument (e.g. `account_id`)
before running it — exactly the intended flow, confirmed end to end
(`summarize_account` correctly asked for the ID and used it). The MCP
Inspector's Prompts tab remains the quickest way to test one during
development, without needing a full client.

Typing the prompt's name as a plain chat message (e.g. literally typing
`summarize_account`) does **not** invoke it — that's just text the model
reads and reacts to conversationally, with no connection to `prompts/get`
at all. This is why it behaves nothing like the real prompt: no specific
Account, no embedded Opportunity/Case data, no enforced `account_id` — just
the model's own judgment call about how to be helpful, which (having full
access to `sf_query`) can include browsing a chunk of Accounts and asking
you to pick one. That's not a bug in the prompt; it's a completely different
code path that happens to share a name with it.

## Subscribing to platform events

### What it is

`sf_subscribe_platform_event` reads events from a Salesforce **platform
event** or **Change Data Capture (CDC)** channel — the things normally
consumed by an Apex trigger, a Flow, or an external subscriber over
Salesforce's Pub/Sub API (the gRPC API that replaced the older CometD-based
Streaming API). Rather than an open-ended live feed, it's a **bounded
batch fetch**: one call connects, collects whatever matches, disconnects,
and returns exactly what it collected — confirmed working end-to-end
against a real Developer Edition org, including both the live-watch and
historical-replay paths described below.

### When to use it

Reach for this when you want to know *what happened* on an event
channel — "show me what was published on `mcp_server_test__e` in the last
hour," "did an `AccountChangeEvent` fire for this record recently" — as
opposed to reacting to events as they happen (that's a job for a real
subscriber: an Apex trigger, a Flow, or a long-running external client;
this tool's each call is bounded and finite by design, see
[ARCHITECTURE.md](ARCHITECTURE.md) for why that's a deliberate choice, not
a limitation to work around).

### How to use it

```
sf_subscribe_platform_event(
    api_name,               # e.g. "mcp_server_test__e", or a full topic
                            # like "/data/AccountChangeEvent" for CDC
    start_time=None,        # ISO 8601 with timezone offset, e.g.
                            # "2026-09-06T02:30:00+00:00"
    end_time=None,          # same format; must be after start_time
    max_events=100,
    timeout_seconds=20,     # capped at 120
)
```

- `api_name` — a bare platform-event API name gets `/event/` prefixed
  automatically (`mcp_server_test__e` → `/event/mcp_server_test__e`). For a
  CDC channel, pass the full topic yourself: `/data/AccountChangeEvent`.
- **Omit `start_time`/`end_time` to watch live** — see "confirmed behavior"
  below for exactly what this returns.
- **Set `start_time` to replay history** — must be within the last 72 hours
  (Salesforce's Pub/Sub API retention window) or the call fails immediately,
  before touching the network, with a clear message naming the limit.
- The call always stops on its own: at `end_time` (if given), at
  `max_events`, or after `timeout_seconds` with nothing new arriving —
  whichever comes first. Check the response's `stopped_reason` to see which.

### Confirmed behavior (tested against a real org)

- **No `start_time`/`end_time`** → the tool watches only for events
  published *during the call itself* (Salesforce's `LATEST` replay
  preset — "tip of the stream," not a query over history). Call it, then
  publish within its `timeout_seconds` window to see something come back.
  Publish before or after that window and it returns
  `{"events_returned": 0, "stopped_reason": "timeout"}` — an empty result
  is the *correct* answer here, not a failure; it simply means nothing new
  arrived while the call was listening.
- **With `start_time` set** → the tool replays from history instead
  (`EARLIEST`), discarding anything published before `start_time` on this
  end (see "How it works" below for why it's done this way). This is the
  path to use for "what already happened" — set `start_time` to comfortably
  before whenever the event was published and it comes back decoded, with
  no need to time the call against a live publish.

**Try it yourself:** create a custom platform event in Setup (Platform
Events → New Platform Event, one Text field is enough), publish a test
event via its own "Publish Platform Events" panel or a couple of lines of
Apex in Developer Console (`EventBus.publish(new Your_Event__e(Your_Field__c
= 'test'))`), then call the tool with `start_time` set to a few minutes
before you published it.

### How it works

Salesforce's Pub/Sub API has no "give me events since timestamp X" — only
`LATEST` (tip of stream), `EARLIEST` (oldest retained event), or `CUSTOM` (a
prior event's own opaque replay ID). So `start_time`/`end_time` are
approximated, not passed to Salesforce directly: `start_time` given →
replay from `EARLIEST` and filter out, on this end, anything published
before it (checking each event's own `CreatedDate`, or
`ChangeEventHeader.commitTimestamp` for a CDC channel); `start_time`
omitted → `LATEST`, live-watch only, nothing retroactive. `end_time` works
the same way in reverse — Salesforce can't stop the stream for you, so the
tool watches each event's timestamp and disconnects once it passes
`end_time`. See
[ARCHITECTURE.md](ARCHITECTURE.md#platform-events-a-tool-not-a-resource-subscription--and-why)
for the full reasoning, including two real bugs found and fixed by testing
this against a live org (a cross-event-loop gRPC channel bug, and a
Salesforce-side quirk where half-closing the request stream silently stops
event delivery entirely).

**If it's not working as expected:** `scripts/diagnose_pubsub.py
<api_name>` bypasses this tool's time-filtering entirely and prints
Salesforce's raw response — `GetTopic`'s `can_subscribe`/`schema_id` (confirms
access and topic existence) and a raw 15-second `EARLIEST` subscribe with
every event or keepalive printed as it arrives. Useful for telling apart "no
events matched my filter" from "nothing is being delivered at all."

## Example prompts → tool calls

| You ask | Tool(s) likely called |
|---|---|
| "What fields does the Opportunity object have?" | `sf_describe_object(sobject="Opportunity")` |
| "Find any record mentioning 'Acme Corp'" | `sf_search(sosl="FIND {Acme Corp} IN ALL FIELDS RETURNING Account(Name), Contact(Name), Opportunity(Name)")` |
| "Create a new Account called 'Acme Test' and log a Contact for it" | `sf_composite(...)` — one atomic call creating both, the Contact referencing the Account via `@{NewAccount.id}` |
| "Upsert this list of leads by their external CRM ID" | `sf_upsert_record` (few records) or `sf_bulk_load(operation="upsert", ...)` (many) |
| "How close are we to today's API limit?" | `sf_api_usage()` |
| "How healthy is our org — any licenses running low?" | `sf_org_health()` |

## Example: a composite request

```json
{
  "requests": [
    {
      "method": "POST",
      "url": "/services/data/v61.0/sobjects/Account",
      "referenceId": "NewAccount",
      "body": { "Name": "Acme Test" }
    },
    {
      "method": "POST",
      "url": "/services/data/v61.0/sobjects/Contact",
      "referenceId": "NewContact",
      "body": { "LastName": "Doe", "AccountId": "@{NewAccount.id}" }
    }
  ]
}
```

## Example: a bulk load

```json
{
  "sobject": "Lead",
  "operation": "upsert",
  "external_id_field": "External_Id__c",
  "records": [
    { "External_Id__c": "ext-1", "LastName": "Doe", "Company": "Acme" },
    { "External_Id__c": "ext-2", "LastName": "Smith", "Company": "Globex" }
  ]
}
```

Returns `{"job_id", "state", "records_processed", "records_failed", "failures"}`
— `failures` is empty on full success, or a list of rows with Salesforce's
`sf__Error` column explaining each one that didn't load.
