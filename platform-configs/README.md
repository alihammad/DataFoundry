# Platform Configurations (GitOps)

This directory is the version-controlled source of truth for deployed
platforms. Changes here flow through Git into update runs (US2).

## Layout

```text
platform-configs/
└── <platform-name>/
    ├── development.yaml
    ├── test.yaml
    ├── uat.yaml
    └── production.yaml
```

- One file per environment type, named exactly after the environment.
- `<platform-name>` must match `platform.name` in the config (lowercase,
  `^[a-z][a-z0-9-]{2,62}$`).
- Configs are cloud-neutral and strict: no plaintext secrets, only
  `secretRef` pointers (SC-006). See `contracts/platform-config-schema.md`.

## Workflow (PR-gated change)

1. Edit the relevant `platform-configs/<platform-name>/<env>.yaml` on a branch.
2. Open a pull request. CI runs `datafoundry validate` on every changed config.
3. After review + merge, the control plane ingests the change
   (`source=git`, `git_ref=<commit>`) and queues an `update` run.

## Examples

Ready-to-use example configs live in `examples/` (see quickstart Scenarios
1–7). They are not part of a deployed platform's GitOps layout.
