# Template: provider version pins for DataFoundry Terraform modules.
#
# Every leaf module under terraform/{aws,gcp}/<capability>/ declares its own
# required_providers with pinned versions (constitution Principle II:
# reproducible from code). This template documents the canonical pins used
# across the repository; the generated per-run workspaces
# (terraform/workspaces/<run_id>/) inherit the same constraints.

terraform {
  required_version = ">= 1.9"

  required_providers {
    # --- AWS modules (terraform/aws/*) ---
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }

    # --- GCP modules (terraform/gcp/*) ---
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }

    # --- Cloud-neutral glue (terraform/modules/*) ---
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}
