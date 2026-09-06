# Releasing (publishing a new version to PyPI)

Pushing commits to `main` — even a lot of them — **never publishes anything
to PyPI by itself.** `.github/workflows/ci.yml` runs lint+tests on every
push/PR, nothing more. Publishing is a separate, deliberate action: pushing
a **git tag matching `v*`** is the only thing that triggers
`.github/workflows/publish.yml`.

## The release checklist

1. **Bump the version** in [`pyproject.toml`](../pyproject.toml)'s
   `[project]` section (`version = "0.1.1"`, say). PyPI permanently rejects
   re-uploading a version number that's ever existed — even one you deleted
   — so this has to be a genuinely new number every time.
2. **Commit and push that bump normally**, like any other change:
   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 0.1.1"
   git push origin main
   ```
   This alone does **not** publish anything — it just runs `ci.yml` like
   any other push.
3. **Tag that commit and push the tag** — this is the actual trigger:
   ```bash
   git tag v0.1.1
   git push origin v0.1.1
   ```
   The tag name must start with `v` (the workflow matches `v*`) and its
   numeric part must exactly match what you just put in `pyproject.toml` —
   `v0.1.1` for `version = "0.1.1"`. This match is enforced by the `build`
   job below, not just a convention.
4. **Watch it run** at
   [github.com/sudhakar6/salesforce-mcp-server/actions](https://github.com/sudhakar6/salesforce-mcp-server/actions) —
   three jobs, in order:
   - `test` — the same lint+pytest gate as `ci.yml`, run again here so a
     publish never proceeds on an untested ref (a tag isn't guaranteed to
     already have a passing `ci.yml` run for that exact commit).
   - `build` — first checks the tag matches `pyproject.toml`'s version
     (fails fast with a clear message if you forgot to bump it, rather than
     letting PyPI's own duplicate-version rejection be the first sign
     something's wrong), then builds the sdist/wheel and hands them to the
     next job as an artifact.
   - `publish` — publishes those artifacts to PyPI using **Trusted
     Publishing** (OIDC) — no API token stored in this repo at all. This
     job runs in the `pypi` GitHub Environment, matching what's configured
     as the trusted publisher on [pypi.org/manage/project/sf-mcp-server/settings/publishing](https://pypi.org/manage/project/sf-mcp-server/settings/publishing/).
5. **Verify it landed**: [pypi.org/project/sf-mcp-server](https://pypi.org/project/sf-mcp-server/)
   should show the new version within a minute or two of the `publish` job
   finishing.

## Things that will make this fail, on purpose

- **Tag doesn't match `pyproject.toml`'s version** — the `build` job's
  first step catches this immediately, before wasting time on a build PyPI
  would reject anyway.
- **Version number already exists on PyPI** (including one you've since
  deleted) — PyPI itself rejects the upload; there's no way around this
  except bumping to a genuinely new number and re-tagging.
- **Trusted publisher config on PyPI doesn't match** (wrong repo owner/name,
  workflow filename, or environment name) — the `publish` job's OIDC
  handshake with PyPI fails. This is a one-time setup already done for this
  project (owner `sudhakar6`, repo `salesforce-mcp-server`, workflow
  `publish.yml`, environment `pypi`) — only relevant again if that config
  ever needs to change (e.g. the workflow file gets renamed).

## What if I just want to test the pipeline without a "real" release?

There isn't a safe way to do this against real PyPI — any tag push that
passes the version-match check *will* actually publish. If you want to
exercise the workflow without committing to a real release, the honest
options are: temporarily point `publish.yml`'s `pypa/gh-action-pypi-publish`
step at TestPyPI instead (`repository-url:
https://test.pypi.org/legacy/`, with its own separate trusted-publisher
config), or just accept that the first "test" of this pipeline is also
your next real release — which is what actually happened the first time
this workflow ran.
