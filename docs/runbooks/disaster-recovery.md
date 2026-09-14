# Runbook: Disaster Recovery

**Feature**: 001-one-click-platform-deployment | **Goal**: SC-002, FR-011

A destroyed platform can be recreated **identically** from its exported
configuration, with zero manual cloud-console steps. This runbook covers the
recovery procedure and the failure modes that lead to it.

## Recovery model

DataFoundry separates two layers of state:

1. **The configuration** (declarative, version-controlled, exported). This is
   the source of truth for *what* a platform is.
2. **The infrastructure** (Terraform-provisioned, per-run state). This is
   disposable — it can be rebuilt from the configuration.

Disaster recovery means: capture the configuration, then rebuild the
infrastructure from it.

## Prerequisite: capture the configuration

Before a platform is lost, export its configuration and keep it in version
control.

```bash
datafoundry export --platform customer-analytics-dev > customer-analytics-dev.yaml
```

Verify the export is secret-free and reproducible:

```bash
gitleaks detect customer-analytics-dev.yaml   # clean
datafoundry validate --config customer-analytics-dev.yaml  # exit 0
```

Commit the export to `platform-configs/` (GitOps source of truth) so it is
never lost with the platform.

## Recovery procedure

```bash
# 1. Confirm the old platform is gone (destroyed or unrecoverable).
datafoundry status --platform customer-analytics-dev

# 2. Redeploy from the exported configuration.
datafoundry deploy --config customer-analytics-dev.yaml --wait

# 3. Verify the recreated platform matches the original.
datafoundry export --platform customer-analytics-dev > recreated.yaml
diff customer-analytics-dev.yaml recreated.yaml   # only timestamps/run ids differ
```

The `config_hash` of the export equals the hash of the redeployed config
version (determinism, SC-002).

## Name-uniqueness note

Destroying a platform releases its `(provider, scope, name)` name, so the
same name can be reused on redeploy. If the original platform still exists
(partial failure rather than full loss), destroy it first, or deploy under a
new name.

## Failure modes and responses

| Failure | Detection | Response |
|---|---|---|
| Cloud account/project deleted | `deploy` fails on credential probe (FR-018 missing permissions) | Recreate the account/project, restore deploy permissions, then redeploy. |
| Config lost (not exported) | No export, no GitOps copy | Rebuild the config by hand from `capabilities-catalog.md` and redeploy; then **immediately** export and commit it. |
| Partial platform (mid-deploy failure) | Run status `failed`; partial state inspectable | `POST /runs/{run_id}/retry` (resume) or `POST /runs/{run_id}/rollback` (clean), then redeploy. |
| Metadata store loss (control plane itself) | Control plane down; platforms still up | Rebuild the control plane (see `bootstrap.md`); platforms are unaffected and can be re-imported by exporting their configs from GitOps. |

## Controls

- **Never** store plaintext secrets in the exported config — the export fails
  closed if any secret material is present (SC-006).
- Recovery requires the same authorisation as deployment (approval for
  production, FR-010).
- Every recovery deploy is recorded in the audit history (who, when, config,
  outcome, duration — FR-014).
