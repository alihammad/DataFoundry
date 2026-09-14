locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "catalog"
  })
}

# GCP catalog capability (T056): OpenMetadata on Cloud Run (R-04) — identical
# logical contract to AWS (http /health target).

resource "google_cloud_run_service" "openmetadata" {
  name     = "${local.name_prefix}-catalog"
  location = var.region

  template {
    spec {
      service_account_name = "datafoundry-${var.platform_name}-${var.environment}-catalog@${data.google_project.current.project_id}.iam.gserviceaccount.com"

      container_concurrency = 80

      containers {
        image = "openmetadata/server:1.5.2"

        env {
          name  = "OM_ENVIRONMENT"
          value = var.environment
        }
        env {
          name  = "DB_SCHEME"
          value = "postgresql"
        }

        ports {
          container_port = 8585
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

data "google_project" "current" {}
