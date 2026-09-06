# Setup

## 1. Get a Salesforce org

Any org works, but for practice use a free
[Developer Edition org](https://developer.salesforce.com/signup) so there's no
risk to real data.

## 2. Create an External Client App

Salesforce restricts creating new legacy **Connected Apps** as of Spring '26.
New integrations should use an **External Client App (ECA)** instead — same
OAuth flows, newer Setup object. This one app can support both auth flows
this server offers, so set both up now even if you only plan to use one:

1. **Setup → search "External Client App Manager" → New External Client App.**
2. Basic Information: give it a name (e.g. "MCP Server Integration"), a
   contact email, and a distribution state of "Local".
3. **API (Enable OAuth Settings):**
   - Check **Enable OAuth**.
   - **Callback URL**: `http://localhost:8765/callback` — this is used for
     real by the default interactive login flow (PKCE), not a throwaway
     placeholder; it must match `SF_PKCE_REDIRECT_PORT` (default `8765`)
     exactly. If you only ever plan to use Client Credentials Flow (which
     ignores this field), any `https://` placeholder works instead.
   - **OAuth Scopes**: add at least `Manage user data via APIs (api)` and
     `Perform requests at any time (refresh_token, offline_access)` (needed
     for the default PKCE flow's refresh tokens).
   - Enable **Authorization Code and Credentials Flow** (for the default
     interactive login) and, if you also want Client Credentials Flow
     available, **Enable Client Credentials Flow** too — check this box
     here if your org shows it on this tab (the exact tab this lives on has
     moved around across Salesforce releases — see the note below).
   - Save.
4. Open the app you just created → **Policies** tab → click **Edit**:
   - For the interactive login (PKCE), find **"Require Secret for Web
     Server Flow"** and **"Require Secret for Refresh Token Flow"** —
     uncheck both for a true secretless public client, or leave them
     checked to also use a Consumer Secret for this flow.
   - If you enabled Client Credentials Flow too, there should be a
     **Client Credentials Flow** section here (sometimes labeled "OAuth
     Flows and External Client App Enhancements") — enable it here as well
     if it's a separate checkbox from Settings, and set **Run As** to a
     dedicated integration user (see step 3 below), *not* your own admin
     user. If you don't see a Run As field yet, it may only appear after
     saving Client Credentials Flow as enabled on the Settings tab first,
     or after setting **Permitted Users** to "Admin approved users are
     pre-authorized" in the same Policies section — try saving once, then
     re-opening Edit.
5. Retrieve credentials: **App → Manage Consumer Details** (may prompt for
   verification) → copy the **Consumer Key** (`SF_CLIENT_ID`). Copy the
   **Consumer Secret** (`SF_CLIENT_SECRET`) too only if you plan to use
   Client Credentials Flow, or left "Require Secret" checked above.

> **Note — this UI moves around.** External Client Apps are a relatively new
> Salesforce feature (GA'd Summer '24) and the exact tab/section for these
> settings has been reported in different places (Settings vs. Policies vs.
> a Policies sub-panel) across releases and org types. If a step above
> doesn't match what you see, look for *any* section mentioning the flow
> name under both the Settings and Policies tabs, click Edit rather than
> just viewing, and check there. Worth double-checking against Salesforce's
> own current help article for your release if this still doesn't line up.

## 3. (Optional — only for Client Credentials Flow) Create a dedicated integration user + permission set

**Skip this step if you're only using the default interactive login** — PKCE
authenticates as whoever logs in, using their own existing permissions; there's
no separate integration user to create.

If you *do* want Client Credentials Flow available (see
[AUTHENTICATION.md](AUTHENTICATION.md) for when that's the better fit), don't
run it as an admin user. Create (or reuse) a user with a minimal license, and
a permission set granting only what the tools need:

- Read/Create/Edit/Delete on the objects you intend to exercise (e.g.
  Account, Contact, Opportunity, or your custom objects)
- API Enabled
- Assign the permission set to that user, then set it as the External Client
  App's "Run As" user (step 2.4 above)

## 4. Find your My Domain login URL

**Setup → My Domain** shows something like
`https://your-domain.my.salesforce.com`. That's `SF_LOGIN_URL` — no trailing
slash, no `/services/...` suffix.

## 5. Configure `.env`

```bash
cp .env.example .env
```

Fill in, at minimum:

```
SF_LOGIN_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=<Consumer Key>
```

That's all the default (interactive login / PKCE) flow needs.
`SF_CLIENT_SECRET` is only required if you're using Client Credentials Flow
instead (`SF_AUTH_FLOW=client_credentials`) — see
[AUTHENTICATION.md](AUTHENTICATION.md) for that option in full.

Leave `SF_API_VERSION` and everything under "Transport" alone for local/stdio
use — see [DEPLOYMENT.md](DEPLOYMENT.md) for the HTTP-mode variables.

One more optional variable, defaulting to on: `SF_ELICITATION_ENABLED=false`
turns off the confirm-before-running checks on unscoped queries/searches and
deletes — see [USAGE.md#elicitation](USAGE.md#elicitation).

## 6. Log in

The default flow requires logging in once before first use:

```bash
source .venv/bin/activate
python -m salesforce_mcp.login
```

This opens your browser to Salesforce's login page and caches a refresh
token locally — see
[AUTHENTICATION.md](AUTHENTICATION.md#salesforce_pkce_tokenjson--what-it-is-and-why-it-matters)
for exactly what this does and why. (Skipped this step, or it's been a
while? A `sf_login` tool is also available from within a running session —
see the same doc.)

**Using Client Credentials Flow instead?** Skip this step entirely — nothing
to log in to, it authenticates automatically.

## 7. Verify the connection

```bash
npx @modelcontextprotocol/inspector python -m salesforce_mcp.server
```

(Installed via `uvx` instead — README's Quickstart Option A? Use
`npx @modelcontextprotocol/inspector uvx sf-mcp-server` instead.)

Open the Inspector's URL, connect, and try `sf_list_objects` — you should see
your org's full object list back.

If you get an authentication error: for the default PKCE flow, the message
will say plainly if no cached login was found (re-run step 6, or call
`sf_login`). For Client Credentials Flow, double check it's enabled on
*both* the Policies and Settings tabs of the External Client App, and that
the Run As user has the permission set assigned.

**If you plan to use `sf_subscribe_platform_event`:** the Pub/Sub API
(platform events / CDC) needs its own access on top of the above, on
whichever Salesforce user is actually authenticating (the integration user
for Client Credentials Flow, or your own user for PKCE) — Salesforce gates
it separately from plain REST API access. We haven't pinned down the exact
permission name/location as it appears in every org edition/release (the
same lesson as the External Client App UI note above); if
`sf_subscribe_platform_event` fails with a permission error, check that
user's profile/permission set for something like "Manage Platform Events"
or CDC-specific access under **Setup → Change Data Capture**, and adjust as
needed for your org.
