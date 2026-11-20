# Bark fork notes

This is Bark's fork of [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp).
It runs as the `mcp-sidecar` container of the Google Workspace MCP service on the
platform EKS cluster, behind the Bark wrapper
([Bark-com/bark-google-workspace-mcp](https://github.com/Bark-com/bark-google-workspace-mcp))
in the same pod. The chart is `google-workspace-mcp/` in
[Bark-com/helm-charts](https://github.com/Bark-com/helm-charts).

The fork is upstream plus **one** Bark commit. Keep it that way: Bark docs live
here and not in `README.md`, so upstream README changes never conflict.

## What the Bark commit adds: WIF + DWD mode

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
  off local file access.

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
gh workflow run deploy.yaml -R Bark-com/google-workspace-mcp --ref <branch> \
  -f environment=platform -f image_tag=v2.6.0-bark.1
```

- Tags are `<upstream version>-bark.<n>`. The workflow refuses an existing tag,
  because the ECR repository is tag-mutable.
- Roll out by opening a helm-charts PR that sets `mcpSidecar.image.tag`, and roll
  back by reverting it.
- Do not dispatch an older revision of this workflow (before v2.6.0-bark.1). It
  wrote `mcp-<sha>` straight into helm-charts and would deploy immediately.

## Moving to a new upstream version

1. Fetch the upstream tag. Push it as branch `upstream/<version>` without tags:
   `git push --no-follow-tags origin <sha>:refs/heads/upstream/<version>`.
2. Branch `bark/<version>` from it and re-apply this commit. Port it by hand where
   upstream moved code; it touches `auth/oauth_config.py`,
   `auth/service_decorator.py`, `core/config.py`, `main.py`,
   `gdrive/drive_helpers.py`, the `tests/**/test_*wif*` and `test_resolve_folder_root`
   files, this file and the workflow.
3. Open a PR into `upstream/<version>` that shows only the Bark commit. Check
   upstream release notes for changes to service-account mode, the bind host and
   tool capabilities. The wrapper's tiering is by tool name, so check renamed and
   new tools too.
4. After merge, build `<version>-bark.1` from `upstream/<version>`, then open the
   helm-charts PR.
