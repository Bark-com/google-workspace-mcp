# Bark fork notes

This is Bark's fork of [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp).
It runs as the `mcp-sidecar` container of the Google Workspace MCP service on the
platform EKS cluster, behind the Bark wrapper
([Bark-com/bark-google-workspace-mcp](https://github.com/Bark-com/bark-google-workspace-mcp))
in the same pod. The chart is `google-workspace-mcp/` in
[Bark-com/helm-charts](https://github.com/Bark-com/helm-charts).

`bark` is the default branch and always holds what is deployed: upstream's
history merged in, plus the Bark auth patch and a few Bark-owned files (the
Dockerfile, `.python-version`, `.trivyignore`, `.github/`, this file). Keep the
patch small: Bark docs live here and not in `README.md`, so upstream README
changes never conflict. The 1.x `main` line is kept only as tag `legacy/main-1.x`.

## What the Bark patch adds: WIF + DWD mode

Upstream supports domain-wide delegation (DWD) only with a service-account key.
Bark runs keyless: Workload Identity Federation (WIF) from EKS, impersonating a
DWD-enabled service account.

The mode is active when `GOOGLE_APPLICATION_CREDENTIALS` and
`GOOGLE_SERVICE_ACCOUNT_EMAIL` are set and no `GOOGLE_SERVICE_ACCOUNT_KEY_FILE` or
`GOOGLE_SERVICE_ACCOUNT_KEY_JSON` is (`auth.oauth_config.is_wif_dwd_mode`).

1. The pod's projected Kubernetes token is exchanged at GCP STS through the WIF
   config in `GOOGLE_APPLICATION_CREDENTIALS`.
2. Those credentials impersonate `GOOGLE_SERVICE_ACCOUNT_EMAIL`, which signs a DWD
   assertion for the Workspace user (`google.auth.impersonated_credentials` with
   `subject`).
3. The subject is the `user_google_email` argument on each tool call. The Bark
   wrapper sets it from the user's verified Okta identity.

### Safety rules (enforced in code)

The subject comes from the caller, so the server must only be reachable by the
wrapper. In WIF mode the server:

- **refuses to start** if it would bind to a non-loopback host (do not set
  `WORKSPACE_MCP_HOST`; upstream's default for this transport is `127.0.0.1`);
- **refuses to start** without `DWD_ALLOWED_DOMAINS`, and rejects any subject
  outside it;
- **refuses to start** with `TRUST_GATEWAY_IDENTITY=true` (upstream's signed-gateway
  model; we don't combine the two);
- ignores `USER_GOOGLE_EMAIL` completely (no default subject, no schema default,
  no server instructions), and fails a call that has no valid `user_google_email`;
- allows `WORKSPACE_MCP_STATELESS_MODE=true` without OAuth 2.1, which also turns
  off local file access;
- requests `drive.file` as-is. Upstream's DWD path swaps it for full `drive`, which
  the Bark DWD client is not authorized for in the Admin console, so every Drive
  write failed with `unauthorized_client` (v2.6.0-bark.1). Under `drive.file`, update
  tools still 404 on files the app did not create. Tools that ask for full `drive`
  themselves (`manage_document_comment`, `manage_spreadsheet_comment`,
  `manage_presentation_comment`) still fail, as they did before v2.6.0.

The Bark commit also accepts `"root"` as a folder without a Drive lookup
(`gdrive.drive_helpers.resolve_folder_id`), because `files.get("root")` can 404 for
delegated users.

### Environment contract (set by the helm chart)

| Variable | Value |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | WIF config path, e.g. `/etc/gcp/wif-config.json` |
| `GOOGLE_SERVICE_ACCOUNT_EMAIL` | the DWD service account |
| `DWD_ALLOWED_DOMAINS` | `bark.com` |
| `MCP_ENABLE_OAUTH21` | `false` |
| `WORKSPACE_MCP_STATELESS_MODE` | `true` |
| `TOOLS` | `drive docs sheets calendar slides gmail` (services the wrapper exposes) |
| `WORKSPACE_MCP_DISABLED_TOOLS` | `manage_calendar` (calendar sharing is not offered) |

Health probes must run inside the container (`curl -fsS http://127.0.0.1:8000/health`),
because the server is not reachable on the pod IP.

## Building an image

`.github/workflows/deploy.yaml` is **build-only**. It does not touch helm-charts.

```bash
gh workflow run deploy.yaml -R Bark-com/google-workspace-mcp --ref bark \
  -f environment=platform -f image_tag=v2.6.0-bark.3
```

- Tags are `<upstream version>-bark.<n>`. The workflow refuses an existing tag,
  because the ECR repository is tag-mutable.
- The image is built on the Bark golden image (`ghcr.io/bark-com/python`, the
  Python line in `.python-version`) and must pass a Trivy HIGH/CRITICAL gate
  before it is pushed. `image-scan.yml` runs the same build and gate on every PR
  into `bark`.
- Upstream's `valkey` extra is not installed: `valkey-glide` has no Alpine
  wheel, and Bark runs stateless with OAuth 2.1 off, so it is never used.
- Roll out by opening a helm-charts PR that sets `mcpSidecar.image.tag`, and roll
  back by reverting it. Any merge into `bark` (an upstream upgrade especially)
  needs a new `-bark.<n>` build before the helm-charts PR: nothing builds on merge.
- Do not dispatch an older revision of this workflow (before v2.6.0-bark.1). It
  wrote `mcp-<sha>` straight into helm-charts and would deploy immediately.

## Automated update PRs

Nobody has to look for updates (PENG-5554). Each source opens a PR into `bark`,
and Platform Engineering is asked to review it through `.github/CODEOWNERS`:

| Source | What | When |
|---|---|---|
| Upstream bot (`upstream-watch.yml` in the wrapper repo) | the newest upstream release | weekly |
| Dependabot | Python security fixes; GitHub Actions updates | as published; weekly |
| Golden Images v1 | new golden base image on the same Python line | when golden images publish |

The wrapper repo also scans both deployed images weekly (`scan-deployed.yml`)
and opens an issue there on HIGH/CRITICAL findings. Nothing merges or deploys
by itself.

Golden-image PRs also add `close-gi-finding.yaml`. It cannot run here, because
this public repo gets no org secrets, so close those DefectDojo findings by hand.

## Moving to a new upstream version

The bot does steps 1 and 2. To run it by hand, dispatch `upstream-watch.yml` in
the wrapper repo with `tag=<version>`.

1. The bot pushes branch `upstream/<version>`: the upstream release commit plus
   one commit that makes `.github/` identical to `bark`'s. Workflows run from
   the branch head, so upstream's own workflow files never run in this repo.
   They would get org-wide AWS access through the shared GitHub OIDC role.
2. It opens a PR from `upstream/<version>` into `bark`, labelled
   `upstream-upgrade`, and lists upstream's `.github/` changes in the PR description.
   Those are never taken.
3. Review what upstream changed. Check the release notes for changes to
   service-account mode, the bind host and tool capabilities. The wrapper's
   tiering is by tool name, so check renamed and new tools too.
4. Resolve conflicts with the Bark patch in the PR, keeping the safety rules
   above. Conflicts are most likely in `auth/oauth_config.py`,
   `auth/service_decorator.py`, `core/config.py`, `main.py`,
   `gdrive/drive_helpers.py` and the Bark-owned files.
5. Merge with **"Create a merge commit"**, never squash or rebase. The bot checks
   whether upstream's release commit is an ancestor of `bark`; a squash breaks
   that check and every later upgrade.
6. Build `<version>-bark.1` from `bark`, then open the helm-charts PR.

## Workflows

Upstream's own workflows (docker-publish, publish-mcp-registry, helm-publish,
check-maintainer-edits) are deleted on `bark` and disabled in the repository
settings for every other ref. Never re-enable them: some publish images or
request cloud credentials. `pytest.yml`, `bark-ruff.yml`, `image-scan.yml` and
`deploy.yaml` are the only workflows that should run. Upstream's `ruff.yml` is
kept unchanged because upstream's tests check its structure, but it triggers
only for `main`, which this fork no longer has.
