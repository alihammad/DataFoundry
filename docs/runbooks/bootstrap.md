# Runbook: Control-Plane Bootstrap

**Feature**: 001-one-click-platform-deployment | **Applies to**: AWS and GCP

Bootstrapping the DataFoundry control plane is a **two-step** operation,
performed once per cloud. The control plane is itself provisioned from
Terraform (`terraform/control-plane/{aws,gcp}/`), after which normal
one-click platform deployment operates as usual.

## Why two steps

The control plane provisions *platforms*, but it cannot provision itself
(no bootstrap chicken-and-egg). Step 1 applies the control-plane bootstrap
module by hand once. Step 2 is everything else: the control plane's normal
`deploy` flow, which requires no manual cloud-console work.

## Prerequisites

- Terraform CLI >= 1.9.8 (see `.terraform-version`).
- Cloud credentials with the permissions listed in the bootstrap module's
  `variables.tf` (documented in the module README).
- A version-control clone of the repository.

## Step 1 — Apply the bootstrap module

### AWS

```bash
cd terraform/control-plane/aws
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

This provisions:

- ECS Fargate service running the control-plane container image.
- RDS PostgreSQL metadata store (KMS-encrypted).
- KMS customer-managed key for the metadata store.
- TLS endpoints for the API (via the load balancer / ACM certificate).

Record the `outputs.api_endpoint` and `outputs.admin_identity` values from
`terraform output`.

### GCP

```bash
cd terraform/control-plane/gcp
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

This provisions:

- Cloud Run service running the control-plane container image.
- Cloud SQL PostgreSQL metadata store (CMEK-encrypted).
- Cloud KMS key for the metadata store.
- TLS endpoint for the API (via the managed HTTPS load balancer).

Record the `outputs.api_endpoint` and `outputs.admin_identity` values from
`terraform output`.

## Step 2 — Normal operation

After bootstrap, the control plane is live and no further bootstrap work is
required. Platform deployment, updates, health checks, export, and destroy
all run through the normal API/CLI flow documented in
`specs/001-one-click-platform-deployment/quickstart.md`.

```bash
# Point the CLI at the bootstrapped endpoint
export DF_API_URL=<outputs.api_endpoint>
export DF_TOKEN=<admin bearer token>
export DF_PROVIDER=aws   # or gcp

datafoundry deploy --config platform-configs/examples/dev-aws-sandbox.yaml --wait
```

## Rollback / teardown

The bootstrap module is a normal Terraform module: `terraform destroy`
removes the control-plane resources. Destroying the control plane does **not**
destroy any platform it deployed — platform resources live in the platform's
own account/project and are managed independently (see
`disaster-recovery.md`).

## Verification

```bash
curl -s <outputs.api_endpoint>/healthz
# Expected: {"status":"ok","version":"..."}
```

If `healthz` is unreachable, check the control-plane service logs and that
the metadata-store security group / private networking allows the control
plane to reach the database.
