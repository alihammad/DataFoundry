check "encryption_enforced_in_production" {
  assert {
    condition     = var.environment != "production" || var.encryption_enforced
    error_message = "FR-017: encryption_enforced must be true in production."
  }
}

locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "semantic"
  })
}

# GCP semantic capability — PLACEHOLDER (T060).
# Full behaviour delivered by feature 006; implements the common contract
# with an endpoint-responds health target.

resource "google_cloud_run_service" "semantic" {
  name     = "${local.name_prefix}-semantic"
  location = var.region

  template {
    spec {
      containers {
        image = "gcr.io/datafoundry-public/semantic:0.1.0"

        ports {
          container_port = 8080
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  labels = local.all_tags
}
