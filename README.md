# Salesforce MCP Server

A custom-built, self-hosted MCP server that lets AI agents (Claude Desktop,
Claude Code, the MCP Inspector, or any other MCP client) connect to
Salesforce — to query, search, and modify data in an org.

> **Not a Salesforce product.** This is an independent, personal learning
> project — not affiliated with, endorsed by, or supported by Salesforce,
> Inc. Full explanation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#not-a-salesforce-product).

> **New to MCP?** If "server," "client," and "tool call" aren't already
> familiar terms, read [docs/MCP_PRIMER.md](docs/MCP_PRIMER.md) first — five
> minutes, and everything else here will make more sense.

## Quickstart

**You'll need:** a Salesforce org with an integration set up — a free
[Developer Edition org](https://developer.salesforce.com/signup) works fine —
and its client ID + secret in hand. [docs/SETUP.md](docs/SETUP.md) walks
through creating that (10–15 min); do it first, then come back here.

Then pick whichever of these you already have installed — both get you to
the same place, a running server:

**Option A — Python 3.11+** (no Docker needed):

```bash
git clone <this-repo-url> && cd salesforce-mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in SF_LOGIN_URL / SF_CLIENT_ID / SF_CLIENT_SECRET
python -m salesforce_mcp.server
```

**Option B — Docker** (no Python setup needed; requires Docker installed
*and running* — check with `docker info`):

```bash
git clone <this-repo-url> && cd salesforce-mcp-server
docker build -t salesforce-mcp-server .
docker run --rm -i \
  -e SF_LOGIN_URL=https://your-domain.my.salesforce.com \
  -e SF_CLIENT_ID=your-client-id \
  -e SF_CLIENT_SECRET=your-client-secret \
  -e MCP_TRANSPORT=stdio \
  salesforce-mcp-server
```

Either way, that's it running. **Next:** point the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) or Claude
Desktop at it and actually try a tool — see [docs/USAGE.md](docs/USAGE.md).

Quick note on that `-e MCP_TRANSPORT=stdio` flag in Option B: **Python vs.
Docker and stdio vs. HTTP are two separate choices, not tied together** —
Python defaults to stdio and Docker's image defaults to HTTP purely for
convenience, but all four combinations actually work. See
[docs/MCP_PRIMER.md#the-two-transports-stdio-and-streamable-http](docs/MCP_PRIMER.md#the-two-transports-stdio-and-streamable-http)
for what each transport actually is and why. For hosting this on a network
instead of running it locally, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## What it can do

- **Query & search** — `sf_query` (SOQL, auto-paginated), `sf_search` (SOSL)
- **Record CRUD** — `sf_get_record`, `sf_create_record`, `sf_update_record`,
  `sf_upsert_record` (by external ID), `sf_delete_record`
- **Bulk API 2.0** — `sf_bulk_query`, `sf_bulk_load`, for record volumes too
  large for the one-record-per-call REST tools above
- **Composite** — `sf_composite`, to bundle several sub-requests into one
  atomic call
- **Describe/discovery** — `sf_describe_object`, `sf_list_objects`, also
  available as MCP **Resources** (`salesforce://objects`,
  `salesforce://schema/{sobject}`)
- **Ops** — `sf_api_usage` (quick API-limit check), `sf_org_health` (fuller
  report: org info, all limits, and license seat usage)
- **Custom APIs** — `sf_call_apex_rest` calls any custom Apex REST endpoint
  (`@RestResource`) your org exposes, no code changes needed — see
  [docs/USAGE.md](docs/USAGE.md#calling-a-custom-apex-rest-api)
- **Resilient by default** — retries transient (5xx / `REQUEST_LIMIT_EXCEEDED`)
  Salesforce errors automatically; every other error comes back as a clean,
  readable message instead of a stack trace

**Every tool above talks to a standard Salesforce API out of the box** — none
of them are specific to any one org. Two ways to add your own: call
`sf_call_apex_rest` (works today, zero code) or add a first-class tool of
your own — [docs/EXTENDING.md](docs/EXTENDING.md) is a step-by-step guide.

## Running it remotely (cloud)

The same server also runs as a container behind a network-reachable
Streamable HTTP endpoint, for when you want an agent that isn't on the same
machine to reach it. **This has been built and run locally with Docker and
confirmed working — it has not yet been deployed to a real cloud account.**
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) has the full picture, including that
caveat up front, plus two ready-to-try recipes (GCP Cloud Run, AWS App
Runner).

## Tests

```bash
pytest tests/ -v      # all Salesforce calls are mocked with respx — no live org needed
ruff check src tests
```

This is the automated suite — fast, no Salesforce org or Docker required.
There are two other, manual checks, each testing something different:
Inspector-against-a-real-org (functional — see [docs/USAGE.md](docs/USAGE.md))
and Docker-build-and-curl (plumbing only — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#build-and-run-locally-first)).

## Documentation

Read in this order if you're getting started:

| # | Doc | For |
|---|---|---|
| 1 | [docs/MCP_PRIMER.md](docs/MCP_PRIMER.md) | New to MCP — what a server/client/tool call actually is |
| 2 | [docs/SETUP.md](docs/SETUP.md) | Creating the Salesforce org + integration, `.env` config |
| 3 | [docs/USAGE.md](docs/USAGE.md) | Running it — Claude Desktop, Claude Code, MCP Inspector, example prompts |
| 4 | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Hosting it in the cloud instead of locally |
| 5 | [docs/EXTENDING.md](docs/EXTENDING.md) | Adding your own tool for a custom API |
| 6 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Optional — how and why it was built this way |

## License

[MIT](LICENSE)
