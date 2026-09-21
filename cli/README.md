# DataFoundry CLI

`datafoundry` command-line client for the DataFoundry control plane.
Part of the DataFoundry monorepo — see `../specs/001-one-click-platform-deployment/`
for design artifacts.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
datafoundry --help
```

## Commands

```text
datafoundry validate --config <path>           # validate a PlatformConfig (all errors at once)
datafoundry deploy   --config <path> [--wait]  # one-click deploy; stream step progress
datafoundry status   --platform <name|id>      # platform + run status
datafoundry export   --platform <name>         # export config (secret-free, reproducible)
datafoundry destroy  --platform <name> [--wait] # destroy a platform
```

## Semantic layer (feature 006)

```text
datafoundry semantic model set --config <path>          # define a semantic model
datafoundry semantic model publish <model_id> [--classification breaking|non_breaking]
datafoundry semantic model approve <publication_id>     # approve a publication
datafoundry semantic test run <test_id>                 # run a semantic test
datafoundry semantic discovery --q "customer revenue"   # search business terms
datafoundry metric query <metric_id> [--dimensions] [--filters] [--as-of]
datafoundry metric describe <metric_id>
datafoundry metric deprecate <metric_id> [--successor <id>] [--period <days>]
```

See `../specs/006-semantic-layer/quickstart.md` for the runnable scenarios
(define/consume, governed lifecycle, access policies, discovery, deprecation).

## Configuration (environment)

| Var | Purpose |
|---|---|
| `DF_API_URL` | Control-plane base URL (default `http://localhost:8000`) |
| `DF_TOKEN` | Bearer token (`cloud_iam` mode) |
| `DF_PROVIDER` | `aws` or `gcp` (`x-datafoundry-provider` header) |

## Layout

```text
src/datafoundry/cli/
├── main.py        # typer app + command wiring
├── client.py      # HTTP client, config loading, RFC 9457 problem rendering
└── commands/      # one module per command (validate, deploy, status, export, destroy)
```

## Error handling

The CLI renders RFC 9457 `application/problem+json` responses as readable
output: each validation error is printed with `path`, `code`, `message`, and
`remediation` (SC-007), and permission failures list the exact missing
permissions (FR-018). Exit codes: `0` success, `1` API/validation failure, `2`
unreadable/invalid local config.
