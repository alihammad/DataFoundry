# DataFoundry Control Plane

FastAPI service that deploys governed lakehouse platforms on AWS/GCP in one click.

Part of the DataFoundry monorepo — see `specs/001-one-click-platform-deployment/` for design artifacts.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

(Full developer guide delivered by task T090.)
