# Setup

## 1. Get a Salesforce org

Any org works, but for practice use a free
[Developer Edition org](https://developer.salesforce.com/signup) so there's no
risk to real data.

## 2. Create an External Client App (Client Credentials Flow)

Salesforce restricts creating new legacy **Connected Apps** as of Spring '26.
New server-to-server integrations should use an **External Client App (ECA)**
instead — same OAuth flow, newer Setup object.

1. **Setup → search "External Client App Manager" → New External Client App.**
2. Basic Information: give it a name (e.g. "MCP Server Integration"), a
   contact email, and a distribution state of "Local".
3. **API (Enable OAuth Settings):**
   - Check **Enable OAuth**.
   - **Callback URL**: required by the form but unused by this flow — any
     `https://` placeholder works, e.g. `https://localhost/callback`.
   - **OAuth Scopes**: add at least `Manage user data via APIs (api)`. Add
     `Perform requests at any time (refresh_token, offline_access)` only if
     you plan to use flows that need it (not required for Client Credentials).
   - **Enable Client Credentials Flow** — check this box here too if your org
     shows it on this tab (the exact tab this lives on has moved around across
     Salesforce releases — see the note below).
   - Save.
4. Open the app you just created → **Policies** tab → click **Edit**:
   - Under **OAuth Policies**, there should be a **Client Credentials Flow**
     section (sometimes labeled "OAuth Flows and External Client App
     Enhancements") — enable it here as well if it's a separate checkbox from
     Settings, and set **Run As** to a dedicated integration user (see step 3
     below), *not* your own admin user.
   - If you don't see a Run As field yet, it may only appear after you've
     saved Client Credentials Flow as enabled on the Settings tab first, or
     after setting **Permitted Users** to "Admin approved users are
     pre-authorized" in the same Policies section — try saving once, then
     re-opening Edit.
5. Retrieve credentials: **App → Manage Consumer Details** (may prompt for
   verification) → copy the **Consumer Key** (`SF_CLIENT_ID`) and **Consumer
   Secret** (`SF_CLIENT_SECRET`).

> **Note — this UI moves around.** External Client Apps are a relatively new
> Salesforce feature (GA'd Summer '24) and the exact tab/section for "enable
> Client Credentials Flow" and "Run As" has been reported in different places
> (Settings vs. Policies vs. a Policies sub-panel) across releases and org
> types. If step 4 doesn't match what you see, look for *any* section
> mentioning "Client Credentials" under both the Settings and Policies tabs,
> click Edit rather than just viewing, and check there for a running-user
> field. Worth double-checking against Salesforce's own current help article
> for your release if this still doesn't line up.

## 3. Create a dedicated integration user + permission set

Don't run this as an admin user. Create (or reuse) a user with a minimal
license, and a permission set granting only what the tools need:

- Read/Create/Edit/Delete on the objects you intend to exercise (e.g.
  Account, Contact, Opportunity, or your custom objects)
- API Enabled
- Assign the permission set to that user, then set it as the External Client
  App's "Run As" user (step 2.4 above)

**If you plan to use `sf_subscribe_platform_event`:** the Pub/Sub API
(platform events / CDC) needs its own access on top of the above — Salesforce
gates it separately from plain REST API access. We haven't pinned down the
exact permission name/location as it appears in every org edition/release
(the same lesson as the External Client App UI note below — don't trust a
fixed screenshot over what's actually in front of you); if `sf_subscribe_platform_event`
fails with a permission error, check the integration user's profile/permission
set for something like "Manage Platform Events" or CDC-specific access under
**Setup → Change Data Capture**, and adjust as needed for your org.

## 4. Find your My Domain login URL

**Setup → My Domain** shows something like
`https://your-domain.my.salesforce.com`. That's `SF_LOGIN_URL` — no trailing
slash, no `/services/...` suffix.

## 5. Configure `.env`

```bash
cp .env.example .env
```

Fill in:

```
SF_LOGIN_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=<Consumer Key>
SF_CLIENT_SECRET=<Consumer Secret>
```

Leave `SF_API_VERSION` and everything under "Transport" alone for local/stdio
use — see [DEPLOYMENT.md](DEPLOYMENT.md) for the HTTP-mode variables.

One more optional variable, defaulting to on: `SF_ELICITATION_ENABLED=false`
turns off the confirm-before-running checks on unscoped queries/searches and
deletes — see [USAGE.md#elicitation](USAGE.md#elicitation).

## 6. Verify the connection

```bash
source .venv/bin/activate
npx @modelcontextprotocol/inspector python -m salesforce_mcp.server
```

Open the Inspector's URL, connect, and try `sf_list_objects` — you should see
your org's full object list back. If you get an authentication error, double
check Client Credentials Flow is enabled on *both* the Policies and Settings
tabs of the External Client App, and that the Run As user has the permission
set assigned.
