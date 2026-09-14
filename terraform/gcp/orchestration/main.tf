locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "orchestration"
  })
}

# GCP orchestration capability (T057): Cloud Composer managed Airflow (R-03);
# airflow /health target.

resource "google_composer_environment" "airflow" {
  name   = "${local.name_prefix}-airflow"
  region = var.region

  config {
    software_config {
      image_version = "composer-2.9.3-airflow-2.9.3"
    }

    workloads_config {
      scheduler {
        cpu        = 1
        memory_gb  = 2
        storage_gb = 5
        count      = 1
      }
      web_server {
        cpu        = 1
        memory_gb  = 2
        storage_gb = 5
      }
      worker {
        cpu        = 1
        memory_gb  = 2
        storage_gb = 5
        min_count  = 1
        max_count  = 3
      }
    }

    environment_size = "ENVIRONMENT_SIZE_SMALL"

    node_config {
      network         = var.network_ref
      subnetwork      = "datafoundry-${var.platform_name}-${var.environment}-private"
      service_account = "datafoundry-${var.platform_name}-${var.environment}-orchestration@${data.google_project.current.project_id}.iam.gserviceaccount.com"
    }

    private_environment_config {
      enable_private_endpoint = true
    }
  }

  labels = local.all_tags
}

data "google_project" "current" {}
