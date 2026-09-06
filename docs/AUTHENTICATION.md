# Authentication: two ways to log in

This server supports two different OAuth 2.0 flows for authenticating to
Salesforce. They solve different problems, they're configured differently
on both the Salesforce side and in this project's `.env`, and — by
design — changing one never requires touching the other (see
[ARCHITECTURE.md#two-auth-flows-kept-deliberately-separate](ARCHITECTURE.md#two-auth-flows-kept-deliberately-separate)
for the code-level reasoning). This doc is the practical "what do I
actually run and configure" reference for both.

| | "Login with Salesforce" (PKCE, default) | Client Credentials Flow |
|---|---|---|
| **What it is** | Interactive: a real person logs in through a real Salesforce login page | Server-to-server: the app itself authenticates as one fixed identity |
| **Who it acts as** | Whoever actually clicked through the login | One shared integration user, for every caller |
| **Setup effort** | One-time Salesforce setup + one login | One-time, in Salesforce Setup |
| **Good for** | Wanting your own Salesforce permissions/visibility reflected, or a "Login with Salesforce" experience | A shared/hosted instance where one fixed identity is fine, or headless environments (Docker) with no browser available |
| **Enable with** | Default — nothing to set | `SF_AUTH_FLOW=client_credentials` |

Everything below covers both in full, including how to switch and how to
tell which one is actually active.

## Option A: "Login with Salesforce" (PKCE, default)

### What it is

OAuth 2.0 Authorization Code flow with PKCE — Salesforce's own recommended
flow for this shape of login (it replaces the older, now-deprecated
User-Agent flow). You personally log in through Salesforce's real login
page in your browser, approve access, and the tokens that come back are
tied to your own Salesforce user — your own permissions, your own
visibility, not a shared integration identity. No separate integration
user or permission set is needed — you're using your own.

### Configuring it in Salesforce

The same External Client App used for Client Credentials Flow can support
both at once — you don't need a second app:

1. Setup → App Manager → your External Client App → **Edit**.
2. Enable **Authorization Code and Credentials Flow** (Client Credentials
   Flow can stay enabled too — they coexist).
3. Under its OAuth policies, find **"Require Secret for Web Server Flow"**
   and **"Require Secret for Refresh Token Flow"**. Uncheck both for a true
   secretless public client (the point of PKCE); leave them checked if
   you'd rather this flow also use a Consumer Secret. (Exact tab/label
   placement varies by release — same caveat as the rest of Setup's UI in
   this project; check both Policies and Settings tabs if you don't see it
   where expected.)
4. Set a **Callback URL** of `http://localhost:8765/callback` — this must
   match `SF_PKCE_REDIRECT_PORT` (default `8765`) exactly.

### Configuring it in `.env`

```
SF_LOGIN_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=<Consumer Key>
```

`SF_AUTH_FLOW` doesn't need to be set at all — `pkce` is the default.
`SF_CLIENT_SECRET` is **optional** in this mode — only include it if you
left "Require Secret" checked above. Two more variables exist with
sensible defaults you'll rarely need to change:

```
SF_PKCE_REDIRECT_PORT=8765            # must match your Callback URL
SF_PKCE_TOKEN_CACHE=.salesforce_pkce_token.json
```

### Two ways to actually log in

**Before starting the server, from a terminal:**

```bash
cd ~/Documents/Salesforce_MCP_server
source .venv/bin/activate
python -m salesforce_mcp.login
```

**Or, from within an already-running session, call the `sf_login` tool.**
It's registered automatically whenever `SF_AUTH_FLOW=pkce`. Call it any
time another tool fails with "no cached PKCE login found," or whenever you
want to log in again as a different Salesforce user (pass `force=true`).
It's self-healing: the model can call it in direct response to that
failure, you complete the login in your browser, and the original call
just works on retry — no need to stop and restart anything.

Either way, the same thing happens:

1. Your default browser opens to Salesforce's real login/consent page.
2. A temporary local listener catches the redirect
   (`http://localhost:8765/callback`).
3. The code is exchanged for tokens.
4. A refresh token is cached to `.salesforce_pkce_token.json`.

The CLI command prints progress as plain text; `sf_login` reports the same
milestones via MCP progress notifications (`ctx.report_progress`) while it
waits for you — up to two minutes, since that's how long the local listener
waits for your browser before giving up. That wait is a **one-time cost**:
it only happens when there's no valid cached login yet (or you asked to
force one), never on every subsequent tool call — those just do a silent
`grant_type=refresh_token` exchange, no browser involved.

**Which to use, in practice:** the CLI command if you're setting this up
for the first time (no MCP client running yet) or want to pre-authenticate
before ever pointing a client at the server; `sf_login` if you're already
mid-session and a call just failed asking you to log in — no context
switch to a terminal required.

### `.salesforce_pkce_token.json` — what it is and why it matters

This file is the entire reason PKCE mode keeps working after that one
login exchange completes. It holds `{"refresh_token": "...", "instance_url":
"..."}` — a long-lived refresh token that the server reads on every
authentication attempt and exchanges for a short-lived access token
(`grant_type=refresh_token`), silently, with no browser and no person
involved. That's what makes "log in once, then just use the server
normally from then on" possible.

A few things that follow directly from that:

- **If it's missing**, PKCE mode fails immediately with a clear error:
  `No cached PKCE login found at ... — run 'python -m salesforce_mcp.login'
  first, then set SF_AUTH_FLOW=pkce.` — that's the signal to log in (either
  the CLI command, or call `sf_login`).
- **It's gitignored and `chmod 600`'d** on creation — treat it exactly like
  a password. Anyone who has this file can authenticate as you until you
  revoke access in Salesforce, without needing your actual Salesforce
  credentials.
- **It can silently change out from under you.** Salesforce can rotate the
  refresh token on every use (an org-level setting); the server detects
  a new one in the response and rewrites this file automatically. You
  never need to do this yourself.
- **Deleting it forces a fresh login** — useful if you want to switch which
  Salesforce user is "logged in" (or just call `sf_login(force=true)`
  instead, which doesn't require touching the file directly), or if you
  suspect it's been compromised (delete it, then also revoke the
  corresponding token in Salesforce Setup → Connected Apps OAuth Usage,
  since deleting the local file doesn't revoke server-side access on its
  own).
- **It is not production-grade secret storage** — a plaintext local file,
  not an OS keychain or secret manager. Fine for personal, local use; a
  known, deliberate limitation of this learning project, not something to
  point at a shared production deployment as-is.

## Option B: Client Credentials Flow

### What it is

The server holds a Consumer Key + Consumer Secret and exchanges them
directly for an access token — no browser, no person logging in. Every
tool call acts as the same fixed Salesforce user (the "Run As" user on the
External Client App), regardless of who's talking to the MCP server. The
right choice for a shared/hosted instance, or anywhere a browser isn't
available — notably **Docker**: PKCE's browser-and-localhost-listener flow
doesn't fit a headless container (no display to open a browser in, and the
callback port would need host mapping), so the Docker quickstart in
[README.md](../README.md) pins this flow explicitly regardless of the
default.

### Configuring it in Salesforce

Covered in full in [SETUP.md](SETUP.md) steps 2–4: an External Client App
with **Client Credentials Flow** enabled, a dedicated integration user with
a minimal permission set (this step is specific to this flow — PKCE
doesn't need it), and that user set as the app's "Run As" user.

### Configuring it in `.env`

```
SF_LOGIN_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=<Consumer Key>
SF_CLIENT_SECRET=<Consumer Secret>
SF_AUTH_FLOW=client_credentials
```

Nothing else to run — start the server (or Inspector) and it authenticates
automatically on first tool call, no login step of any kind.

## How to tell which flow actually ran

Both flows fail differently, which makes for a reliable way to confirm
which one is active without adding any special "which mode am I in" tool:
temporarily rename `.salesforce_pkce_token.json` (e.g. append `.bak`) and
make one tool call.

- **PKCE really is active** if that call now fails with the specific
  `No cached PKCE login found ...` message.
- **Client Credentials Flow is active** if the call succeeds anyway — that
  mode never looks at this file at all.

Restore the filename afterward (`mv ... .bak ...` back) either way.

## Troubleshooting — real errors, worked examples

**`SF_AUTH_FLOW must be one of ('client_credentials', 'pkce'), got '...'`**
— a typo in `.env` (e.g. `cleint_credentials`). The server validates this
value strictly at startup rather than silently falling back to a default;
fix the spelling.

**`No cached PKCE login found at ... — run 'python -m salesforce_mcp.login'
first...`** — exactly what it says: run the login command, or call
`sf_login`. Also the correct, expected result of the "how to tell which
flow ran" test above.

**Login hangs, then times out after 120 seconds** (CLI or `sf_login`
alike) — the local callback listener never received a redirect. Check
nothing else is bound to the port (`lsof -i :8765`), and that the Callback
URL configured in Setup matches
`http://localhost:{SF_PKCE_REDIRECT_PORT}/callback` exactly.

**`SF_CLIENT_SECRET is required when SF_AUTH_FLOW=client_credentials`** —
you switched to Client Credentials Flow without setting a secret (or
removed it while previously testing PKCE mode).
