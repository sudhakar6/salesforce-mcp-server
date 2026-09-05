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

Add to Claude Desktop's MCP config
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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
  }
}
```

Restart Claude Desktop, then ask it something that needs Salesforce data —
e.g. *"List the open opportunities over $10,000 closing this quarter"* or
*"Find every Account or Contact mentioning 'Acme'"* (exercises `sf_search`).

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

**Client support, tested directly rather than assumed:** the server side is
confirmed correct — `initialize` advertises the `prompts` capability and
`prompts/list` returns all three with full schemas over the real stdio wire
protocol (verified with a raw JSON-RPC probe, not just an in-process check).
But **none of the three clients tested — Claude Desktop's regular chat tab,
its Code tab, or the standalone Claude Code CLI — currently surface a UI for
invoking an MCP Prompt** (no `/`-menu entry, no `/mcp__server__prompt`
despite that format being documented elsewhere for Claude Code). This lines
up with Prompts being, by a wide margin, the least-implemented part of MCP
across clients generally — not specific to this server.

**Today, the MCP Inspector's Prompts tab is the only confirmed way to invoke
these directly.** Typing the prompt's name as a plain chat message (e.g.
literally typing `summarize_account`) does **not** invoke it either — that's
just text the model reads and reacts to conversationally, with no connection
to `prompts/get` at all, which is why it behaves nothing like the real
prompt (no specific Account, no embedded Opportunity/Case data — just the
model's own guess at achieving something similar via `sf_query`).

If a client you're using ever adds prompt-picker support, revisit this —
the tools/prompts data on the server side is already correct and won't need
to change.

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
