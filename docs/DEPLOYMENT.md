# Deployment

The server runs locally via stdio by default (see [USAGE.md](USAGE.md)). This
doc covers the second mode: packaged as a container and hosted somewhere
reachable over the network, using MCP's **Streamable HTTP** transport.

> ⚠️ **Tested locally only — not yet verified on a live cloud account.**
> Everything below was built and checked on this machine: the Docker image
> builds, runs, and its auth gate works correctly (see "Build and run locally
> first"). The two cloud recipes are written to be correct and are based on
> each platform's real, documented CLI commands, but **neither has actually
> been run against a live GCP or AWS account**. Follow them, but verify each
> step yourself rather than assuming they'll work first try — cloud-specific
> details (IAM, quotas, region availability) can't be fully tested without an
> account to test against.

## Two modes, one image

*What "stdio" and "Streamable HTTP" actually mean, mechanically:
[MCP_PRIMER.md#the-two-transports-stdio-and-streamable-http](MCP_PRIMER.md#the-two-transports-stdio-and-streamable-http).*

| | Where it runs | Who talks to it | Covered in |
|---|---|---|---|
| **stdio** (default) | Your machine, spawned by the client | Claude Desktop, Claude Code, MCP Inspector | [USAGE.md](USAGE.md) |
| **Streamable HTTP** (this doc) | Anywhere that runs a container | Any MCP client, over the network, with a bearer token | Below |

Same code, same Docker image — just a different transport, picked with one
environment variable (`MCP_TRANSPORT`).

## The container is platform-agnostic by design

The [Dockerfile](../Dockerfile) has no cloud-vendor SDKs and no
platform-specific code baked in — just Python, the package, and a plain HTTP
listener. It's configured entirely through environment variables:

| Variable | Required | Meaning |
|---|---|---|
| `SF_LOGIN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET` | yes | Salesforce auth — see [SETUP.md](SETUP.md) |
| `MCP_TRANSPORT` | yes, set to `http` | Switches from stdio to Streamable HTTP |
| `MCP_SERVER_TOKEN` | yes (enforced at startup when `MCP_TRANSPORT=http`) | Shared secret; clients must send `Authorization: Bearer <this>` |
| `PORT` | no, defaults to `8080` | Most container platforms inject this automatically |
| `MCP_HOST` | no, defaults to `0.0.0.0` | Bind address |
| `SF_API_VERSION` | no, defaults to `v61.0` | Salesforce REST API version |

Anything that can run an OCI container image and set environment variables can
host this: Cloud Run, AWS App Runner or Fargate, Fly.io, Render, Railway, a
bare VM, or a Kubernetes cluster. Two concrete recipes are below to prove that
portability claim, not because those are the only two options.

Generate a server token once with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Build and run locally first

**Prerequisite:** Docker needs to be *installed and running* — the CLI can be
present with no daemon behind it, which fails with a "cannot connect to the
Docker API" error. Check with `docker info`; if that fails, start
[Docker Desktop](https://www.docker.com/products/docker-desktop/), or on
macOS/Linux a lighter CLI-only alternative like
[Colima](https://github.com/abiosoft/colima) (`colima start`) works too.

**What this checks, and what it doesn't:** these commands use fake
credentials on purpose — they confirm the container builds, starts, and that
the bearer-token gate correctly returns 401/200. They do **not** exercise any
real Salesforce tool call. For that, use the MCP Inspector against your real
`.env` credentials instead (see [USAGE.md](USAGE.md)) — the two check
different things and neither substitutes for the other.

```bash
docker build -t salesforce-mcp-server .
docker run -p 8080:8080 \
  -e SF_LOGIN_URL=https://your-domain.my.salesforce.com \
  -e SF_CLIENT_ID=your-client-id \
  -e SF_CLIENT_SECRET=your-client-secret \
  -e MCP_SERVER_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  salesforce-mcp-server
```

Verify the auth gate works before deploying anywhere:

```bash
# No token — expect 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"initialize","id":1}'

# With the correct token — expect a real MCP response
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <your token>" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

✅ This exact sequence — build, run, both curl checks — is what was actually
run and confirmed working during development. Everything from here on
(the two cloud recipes) is documented but not yet deployed to a real account
— see the warning at the top of this page.

## Recipe: GCP Cloud Run

```bash
gcloud run deploy salesforce-mcp-server \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars SF_LOGIN_URL=https://your-domain.my.salesforce.com,SF_CLIENT_ID=...,MCP_TRANSPORT=http \
  --set-secrets SF_CLIENT_SECRET=sf-client-secret:latest,MCP_SERVER_TOKEN=mcp-server-token:latest
```

- `--allow-unauthenticated` is about *Cloud Run's own* IAM layer, not this
  server's auth — the bearer-token middleware still gates every request
  regardless. Prefer Secret Manager (`--set-secrets`) over plain env vars for
  `SF_CLIENT_SECRET` and `MCP_SERVER_TOKEN`.
- Cloud Run sets `PORT` automatically; nothing else to configure for that.

## Recipe: AWS App Runner

```bash
# 1. Push the image to ECR
aws ecr create-repository --repository-name salesforce-mcp-server
docker tag salesforce-mcp-server:latest <account-id>.dkr.ecr.<region>.amazonaws.com/salesforce-mcp-server:latest
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/salesforce-mcp-server:latest

# 2. Create the App Runner service (or use the console) pointing at that image,
#    with environment variables SF_LOGIN_URL / SF_CLIENT_ID / MCP_TRANSPORT=http
#    set directly, and SF_CLIENT_SECRET / MCP_SERVER_TOKEN as App Runner
#    "secrets" backed by AWS Secrets Manager rather than plain env vars.
```

App Runner also injects `PORT` (default `8080`) — same container, no changes
needed versus the Cloud Run recipe.

## Connecting an agent to it

Deploying gets you a URL and a token; it doesn't by itself get an agent
talking to it. That part — and a real gap in Claude Desktop's support for
this server's simple bearer-token auth specifically — is covered in
[USAGE.md#connecting-an-agent-to-a-remote-hosted-server](USAGE.md#connecting-an-agent-to-a-remote-hosted-server).

## A note on the SDK's DNS-rebinding protection

The `mcp` SDK auto-enables Host/Origin allowlisting only when bound to
`127.0.0.1`/`localhost` (this server defaults to `0.0.0.0`, so it's off by
default here — see [ARCHITECTURE.md](ARCHITECTURE.md#server-side-auth-is-separate-from-salesforce-auth)).
The bearer-token gate is the primary defense for a hosted instance. For extra
defense-in-depth behind a known domain, you can pass a
`TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` into
`streamable_http_app()` in `server.py` — not required, but available.
