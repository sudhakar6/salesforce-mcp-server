# MCP, in brief

This project assumes some familiarity with the Model Context Protocol. If
you're new to it, this page is the 5-minute version; the
[official spec and docs](https://modelcontextprotocol.io) are the full
reference.

## What MCP is, and why it exists

Before MCP, every AI application that wanted to use, say, a Salesforce
integration, a GitHub integration, and a filesystem integration had to
implement each one from scratch, in whatever shape that AI app's own plugin
system demanded. **Model Context Protocol (MCP)** is an open, vendor-neutral
standard (originated by Anthropic, now developed openly) that fixes this by
defining one protocol for "an AI application talks to an external
tool/data source." Anthropic's own framing is "USB-C for AI applications" —
one connector shape, so anything speaking it can plug into anything else
speaking it, instead of a custom cable per pair.

Concretely, that means **this Salesforce server was written once, against
the open spec, and works with any MCP-compatible AI application** — Claude
Desktop, Claude Code, the MCP Inspector, or a future client that doesn't
exist yet — without this project needing to know or care which one is
calling it.

## The three roles: Host, Client, Server

```
┌─────────────────────────────┐
│  Host (e.g. Claude Desktop)  │   the AI application the human uses
│  ┌─────────────────────────┐│
│  │ Client                  ││   lives inside the host; owns exactly
│  │ (1 per connected server)││   one connection to one server
│  └───────────┬─────────────┘│
└──────────────┼──────────────┘
               │ MCP protocol (JSON-RPC 2.0)
               │ — stdio (local process) or Streamable HTTP (network) —
               ▼
┌──────────────────────────────┐
│  Server (this project)       │   exposes Tools / Resources / Prompts;
│  salesforce_mcp.server        │   has no idea what LLM, if any, is on
└──────────────────────────────┘   the other end of the client

```

- **Host** — the application a person actually opens: Claude Desktop, Claude
  Code, an IDE, etc. It's what has the LLM and the conversation.
- **Client** — the part of the host that speaks MCP. A host holds one client
  per connected server, each a private, stateful, 1:1 connection — a client
  never talks to two servers over the same connection, and a server never
  knows about other servers the host might also be connected to.
- **Server** — this project. It advertises capabilities (Tools, Resources,
  and optionally Prompts) and executes them on request. A server has no idea
  which model, if any, is driving the conversation on the other end — it just
  answers protocol requests.

Why the split matters in practice: it's what lets one Salesforce server
(this repo) be useful to Claude Desktop today, a different MCP-compatible
agent tomorrow, and an automated test harness (the MCP Inspector) in between
— all without changing a line of `salesforce_mcp` code.

## The two transports: stdio and Streamable HTTP

The diagram above says the client and server talk over "stdio (local
process) or Streamable HTTP (network)." Those are the two ways the JSON-RPC
messages in this doc actually travel between them:

- **stdio** — the host launches the server directly as a child process, and
  the two talk over that process's stdin/stdout pipes. Same plumbing as
  `cmd1 | cmd2` on a command line. No network, no port; the server only
  exists for as long as the host keeps that process running. This is why
  Claude Desktop's config is a `"command"` + `"args"` (see
  [USAGE.md](USAGE.md)) — that's the literal command line used to start it.
  Simplest option, and there's no listening port to secure, which is why
  it's this server's default for local use.
- **Streamable HTTP** — the server instead runs continuously as its own web
  server on a port (this one uses `/mcp`), and *any* client that has the URL
  can reach it over the network, not just something on the same machine.
  That's what makes hosting it in the cloud useful: deploy once, and any
  agent anywhere can connect to the same running instance (see
  [DEPLOYMENT.md](DEPLOYMENT.md)). It also means the server needs its own
  access control now — stdio's is implicit (only whoever can launch the
  process can use it), but a network listener has no such boundary on its
  own, which is why this mode requires a bearer token
  (see [ARCHITECTURE.md](ARCHITECTURE.md#server-side-auth-is-separate-from-salesforce-auth)).

This server can run either way — `MCP_TRANSPORT=stdio` (default) or
`MCP_TRANSPORT=http` — same code, same tools, just a different way for a
client to reach it. Both are part of the MCP spec itself, not something this
project invented — see the official
[Transports specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
for the full protocol-level detail.

**This is a separate choice from Python vs. Docker.** It's tempting to
assume "Python venv = stdio" and "Docker = HTTP" since that's what
[README.md](../README.md)'s Quickstart defaults to for each — but that's
just a sensible default, not a rule. All four combinations work, verified
directly:

| | stdio | Streamable HTTP |
|---|---|---|
| **Python venv** | ✅ Quickstart's Option A | ✅ same code, just set `MCP_TRANSPORT=http` |
| **Docker** | ✅ Quickstart's Option B (`-e MCP_TRANSPORT=stdio`) | ✅ the image's built-in default, used in [DEPLOYMENT.md](DEPLOYMENT.md) |

`MCP_TRANSPORT` alone decides the transport. Python vs. Docker only decides
*how the process starts* — a venv command vs. a container — which is a
completely separate question.

## How a tool call actually happens

This is the mechanism behind the configs shown in [USAGE.md](USAGE.md):

1. **Connection + discovery.** When the host starts (or you add the server),
   its client connects and sends `initialize`, then `tools/list` (and
   `resources/list`). The server responds with every tool's name,
   description, and JSON Schema for its parameters — e.g. `sf_query`'s
   description and its `soql: string` parameter.
2. **The model sees that list.** The host feeds the tool list to the LLM as
   part of its context, alongside your message. The model itself decides,
   from your natural-language request and each tool's description, whether a
   tool is relevant and which one — nothing in this server tells the model
   when to call it; the tool descriptions in `tools/*.py`'s docstrings *are*
   the model's only guide, which is why they're written for the model, not
   just for humans reading the code.
3. **The client sends `tools/call`.** If the model decides to call
   `sf_query`, the host's client sends a `tools/call` JSON-RPC request with
   the tool name and the arguments the model generated (e.g.
   `{"soql": "SELECT Id, Name FROM Account LIMIT 5"}`).
4. **The server executes and replies.** `salesforce_mcp` runs the actual
   Salesforce REST call and returns the result (or a `ToolError` message —
   see [ARCHITECTURE.md](ARCHITECTURE.md#error-handling)) as the `tools/call`
   response.
5. **The model continues reasoning** with that result now in context —
   possibly calling another tool, or just answering you.

Resources (`salesforce://objects`, `salesforce://schema/{sobject}`) skip
steps 2–3 of that model-decides dance: a client can just read one directly
(`resources/read`) and hand it to the model as context up front, which is
why [ARCHITECTURE.md](ARCHITECTURE.md#describe-discovery-as-both-a-tool-and-a-resource)
treats Resources as a distinct thing from Tools rather than a redundant copy.

## Further reading

- [modelcontextprotocol.io](https://modelcontextprotocol.io) — the official
  site: spec, concepts, and client/server SDK docs
- [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) —
  the SDK this server is built on
- [github.com/modelcontextprotocol/inspector](https://github.com/modelcontextprotocol/inspector) —
  the debugging tool used throughout [USAGE.md](USAGE.md)
