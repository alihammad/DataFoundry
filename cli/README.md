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
